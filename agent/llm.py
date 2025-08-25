import os
from datetime import datetime

import anthropic
from anthropic import RateLimitError, APIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from flask import current_app
from flask_socketio import emit

from tools.bash_tool import bash_tool
from tools.sqlite_tool import sqlite_tool
from tools.ipython_tool import ipython_tool
from tools.todo_tools import (
    create_todo_tool,
    update_todo_tool,
    list_todos_tool,
    search_todos_tool,
    get_todo_tool,
    delete_todo_tool,
    get_todo_stats_tool,
)
from tools.github_rag_tools import (
    github_rag_index_tool,
    github_rag_query_tool,
    github_rag_list_tool,
)
from github_rag import GitHubRAG

from .session_manager import sessions
from .mcp_client import get_mcp_client


class LLM:
    def __init__(self, model, session_id=None):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise ValueError("ANTHROPIC_API_KEY environment variable not found.")
        self.client = anthropic.Anthropic()
        self.model = model
        self.session_id = session_id
        self.messages = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
        self.system_prompt = self._build_system_prompt()
        self.tools = [
            bash_tool,
            sqlite_tool,
            ipython_tool,
            create_todo_tool,
            update_todo_tool,
            list_todos_tool,
            search_todos_tool,
            get_todo_tool,
            delete_todo_tool,
            get_todo_stats_tool,
            github_rag_index_tool,
            github_rag_query_tool,
            github_rag_list_tool,
        ]

        # Add MCP tools if global MCP client is available
        self._add_mcp_tools()

    def _add_mcp_tools(self):
        """Add MCP tools from the global MCP client if available"""
        try:
            mcp_client = get_mcp_client()
            if mcp_client and mcp_client.is_initialized:
                mcp_tools = mcp_client.get_tools_for_anthropic()
                self.tools.extend(mcp_tools)
        except Exception:
            # Silently ignore errors to avoid breaking initialization
            pass

    def _build_system_prompt(self):
        """Build the system prompt dynamically including RAG repository information."""
        base_prompt = ""

        # Add RAG repository information if available
        rag_info = self._get_rag_repositories_info()
        if rag_info:
            base_prompt += rag_info + "\n\n"

        # Add custom system prompt if configured
        try:
            if "SYSTEM_PROMPT" in current_app.config and current_app.config["SYSTEM_PROMPT"]:
                base_prompt += current_app.config["SYSTEM_PROMPT"]
        except RuntimeError:
            # Working outside of application context, skip Flask config
            pass

        print("SYSTEM PROMPT:", base_prompt)

        return base_prompt

    def _get_rag_repositories_info(self):
        """Get information about available RAG repositories."""
        try:
            if self.session_id and self.session_id in sessions:
                if "github_rag" not in sessions[self.session_id]:
                    # Try to initialize GitHub RAG to check for existing repositories
                    openai_api_key = os.environ.get("OPENAI_API_KEY")
                    if openai_api_key:
                        sessions[self.session_id]["github_rag"] = GitHubRAG(
                            openai_api_key
                        )
                    else:
                        return None

                github_rag = sessions[self.session_id]["github_rag"]
                repositories = github_rag.list_repositories()

                if repositories:
                    rag_info = "INDEXED RAG REPOSITORIES:\n"
                    rag_info += "The following GitHub repositories are available for querying:\n"
                    for repo in repositories:
                        rag_info += f"- {repo['repo_name']} (collection: {repo['collection_name']}) - {repo['document_count']} files, {repo['chunk_count']} chunks\n"
                    rag_info += "Use github_rag_query with the collection name to ask questions about these repositories."
                    return rag_info
        except Exception:
            # Silently ignore errors to avoid breaking initialization
            # This includes cases where sessions are not available (e.g., in tests)
            pass

        return None

    def refresh_system_prompt(self):
        """Refresh the system prompt to include newly indexed repositories."""
        self.system_prompt = self._build_system_prompt()

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _call_anthropic(self, stream=False):
        return self.client.messages.create(
            model=self.model,
            max_tokens=64_000,
            system=self.system_prompt,
            messages=self.messages,
            tools=self.tools,
            stream=stream,
            timeout=600.0,  # 10 minutes timeout for long operations
        )

    def summarize_image(self, image_data, filename):
        """Summarize an image using a separate LLM call to save tokens."""
        print(f"Summarizing image: {filename}")

        # Detect image format from base64 data
        media_type = "image/png"  # default
        try:
            # Check the first few bytes of the decoded data to determine format
            import base64
            header = base64.b64decode(image_data[:100])  # Just check header
            
            # JPEG magic bytes: FF D8 FF
            if header[:3] == b'\xff\xd8\xff':
                media_type = "image/jpeg"
            # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
            elif header[:8] == b'\x89PNG\r\n\x1a\n':
                media_type = "image/png"
            # GIF magic bytes: GIF87a or GIF89a
            elif header[:6] in (b'GIF87a', b'GIF89a'):
                media_type = "image/gif"
            # WebP magic bytes: RIFF....WEBP
            elif header[:4] == b'RIFF' and header[8:12] == b'WEBP':
                media_type = "image/webp"
                
            print(f"Detected image format: {media_type}")
        except Exception as e:
            print(f"Could not detect image format, using default: {e}")

        # Create a simple client for image summarization
        temp_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Please provide a detailed description of this image ({filename}). Focus on the key visual elements, text content, UI elements, code, diagrams, or any other important details that would be useful for an AI assistant helping with programming tasks.",
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                ],
            }
        ]

        try:
            response = self.client.messages.create(
                model="claude-opus-4-1-20250805",  # Use latest Claude for best image understanding
                max_tokens=1000,
                system="You are an expert at describing images in detail. Provide comprehensive descriptions that would help an AI assistant understand the content.",
                messages=temp_messages,
            )
            summary = response.content[0].text
            print(f"Image summary generated: {len(summary)} chars")
            return summary
        except Exception as e:
            print(f"Error summarizing image: {e}")
            return f"[Image: {filename} - Could not generate summary: {str(e)}]"

    def _call_with_streaming(self, stream_callback):
        """Handle streaming responses."""
        print("Starting streaming response...")

        response_text = ""
        tool_calls = []
        input_tokens = 0
        output_tokens = 0

        try:
            with self._call_anthropic(stream=True) as stream:
                for event in stream:
                    if event.type == "message_start":
                        input_tokens = event.message.usage.input_tokens

                    elif event.type == "content_block_start":
                        if event.content_block.type == "text":
                            pass  # Text block starting
                        elif event.content_block.type == "tool_use":
                            tool_calls.append(
                                {
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input": event.content_block.input,
                                }
                            )

                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            chunk = event.delta.text
                            response_text += chunk
                            # Stream to callback
                            if stream_callback:
                                stream_callback(chunk, "content")
                        elif event.delta.type == "input_json_delta":
                            # Tool input is being streamed
                            pass

                    elif event.type == "message_delta":
                        if hasattr(event.delta, "stop_reason"):
                            print(f"Stream finished: {event.delta.stop_reason}")

                    elif event.type == "message_stop":
                        # Handle different API versions - some have usage directly on event
                        if hasattr(event, "usage") and event.usage:
                            output_tokens = event.usage.output_tokens
                        elif hasattr(event, "message") and hasattr(
                            event.message, "usage"
                        ):
                            output_tokens = event.message.usage.output_tokens

        except Exception as e:
            print(f"Streaming error: {e}")
            raise

        # Update token usage
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_tokens = self.total_input_tokens + self.total_output_tokens

        # Emit token usage update
        if stream_callback:
            try:
                from flask import session as flask_session

                session_id = flask_session.get("session_id")
                if session_id:
                    emit(
                        "token_usage_update",
                        {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_input_tokens": self.total_input_tokens,
                            "total_output_tokens": self.total_output_tokens,
                            "total_tokens": self.total_tokens,
                            "timestamp": datetime.now().isoformat(),
                        },
                        room=session_id,
                    )
            except:
                # Ignore if not in web context or Flask context unavailable
                pass

        # Return response text and tool calls
        return response_text, tool_calls

    def _remove_cache_control(self):
        """Safely remove cache_control from the user message."""
        if not self.messages:
            return

        # Find the most recent user message
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                user_message = self.messages[i]
                if (
                    isinstance(user_message.get("content"), list)
                    and len(user_message["content"]) > 0
                ):
                    last_content = user_message["content"][-1]
                    if (
                        isinstance(last_content, dict)
                        and "cache_control" in last_content
                    ):
                        del last_content["cache_control"]
                        print(f"DEBUG: Removed cache_control from user message")
                break

    def _validate_message_structure(self, skip_active_tools=True):
        """Validate message structure to prevent orphaned tool_result blocks.

        Args:
            skip_active_tools: If True, skip validation if there are recent tool_use blocks
                              that may still be waiting for results.
        """
        if not self.messages:
            return

        print(f"DEBUG: Validating message structure with {len(self.messages)} messages")

        # If skip_active_tools is True, check for recent tool_use blocks without results
        if skip_active_tools and len(self.messages) >= 2:
            last_message = self.messages[-1]
            if last_message.get("role") == "assistant" and isinstance(
                last_message.get("content"), list
            ):
                # Check if last assistant message has tool_use blocks
                has_tool_use = any(
                    (isinstance(c, dict) and c.get("type") == "tool_use")
                    or (hasattr(c, "type") and c.type == "tool_use")
                    for c in last_message["content"]
                )
                if has_tool_use:
                    print(
                        "DEBUG: Skipping validation - recent tool_use blocks may still be active"
                    )
                    return

        # Print all messages for debugging
        for i, msg in enumerate(self.messages):
            print(
                f"DEBUG: Message {i}: role={msg.get('role')}, content_type={type(msg.get('content'))}"
            )
            if isinstance(msg.get("content"), list):
                for j, content in enumerate(msg["content"]):
                    content_type = (
                        content.get("type")
                        if isinstance(content, dict)
                        else getattr(content, "type", "unknown")
                    )
                    if content_type == "tool_use":
                        tool_id = (
                            content.get("id")
                            if isinstance(content, dict)
                            else getattr(content, "id", "unknown")
                        )
                        print(
                            f"DEBUG:   Content {j}: {content_type} with ID: {tool_id}"
                        )
                    elif content_type == "tool_result":
                        tool_use_id = (
                            content.get("tool_use_id")
                            if isinstance(content, dict)
                            else getattr(content, "tool_use_id", "unknown")
                        )
                        print(
                            f"DEBUG:   Content {j}: {content_type} with tool_use_id: {tool_use_id}"
                        )
                    else:
                        print(f"DEBUG:   Content {j}: {content_type}")

        # Check for orphaned tool_result blocks
        for i, message in enumerate(self.messages):
            if message.get("role") == "user" and isinstance(
                message.get("content"), list
            ):
                tool_results = [
                    c for c in message["content"] if c.get("type") == "tool_result"
                ]
                if tool_results:
                    print(
                        f"DEBUG: Found {len(tool_results)} tool_result blocks in message {i}"
                    )

                    # Look for corresponding tool_use blocks in previous assistant messages
                    tool_use_ids = set()

                    # Search backwards for the most recent assistant message with tool_use blocks
                    for j in range(i - 1, -1, -1):
                        prev_message = self.messages[j]
                        print(
                            f"DEBUG: Checking message {j}: role={prev_message.get('role')}"
                        )

                        if prev_message.get("role") == "assistant":
                            prev_content = prev_message.get("content", [])
                            print(
                                f"DEBUG: Assistant message content type: {type(prev_content)}"
                            )
                            if isinstance(prev_content, list):
                                for c in prev_content:
                                    if hasattr(c, "type") and c.type == "tool_use":
                                        tool_id = getattr(c, "id", None)
                                        if tool_id:
                                            tool_use_ids.add(tool_id)
                                            print(
                                                f"DEBUG: Found tool_use with ID: {tool_id}"
                                            )
                                    elif (
                                        isinstance(c, dict)
                                        and c.get("type") == "tool_use"
                                    ):
                                        tool_id = c.get("id")
                                        if tool_id:
                                            tool_use_ids.add(tool_id)
                                            print(
                                                f"DEBUG: Found tool_use with ID: {tool_id}"
                                            )
                            break  # Stop at first assistant message found

                    print(f"DEBUG: All valid tool_use IDs found: {tool_use_ids}")

                    # If no tool_use blocks found, remove ALL tool_result blocks
                    if not tool_use_ids:
                        print(
                            f"DEBUG: No tool_use blocks found - removing ALL {len(tool_results)} tool_result blocks"
                        )
                        original_count = len(message["content"])
                        valid_content = []
                        removed_count = 0
                        for content_block in message["content"]:
                            if content_block.get("type") == "tool_result":
                                print(
                                    f"DEBUG: Removing orphaned tool_result with ID: {content_block.get('tool_use_id')}"
                                )
                                removed_count += 1
                                continue
                            valid_content.append(content_block)
                        message["content"] = valid_content
                        print(
                            f"DEBUG: Removed {removed_count} orphaned tool_results. Content blocks: {original_count} -> {len(valid_content)}"
                        )
                    else:
                        # Remove only orphaned tool_results
                        original_count = len(message["content"])
                        valid_content = []
                        removed_count = 0
                        for content_block in message["content"]:
                            if content_block.get("type") == "tool_result":
                                tool_result_id = content_block.get("tool_use_id")
                                print(
                                    f"DEBUG: Checking tool_result with ID: {tool_result_id}"
                                )
                                if tool_result_id not in tool_use_ids:
                                    print(
                                        f"DEBUG: Removing orphaned tool_result with ID: {tool_result_id}"
                                    )
                                    removed_count += 1
                                    continue
                                else:
                                    print(
                                        f"DEBUG: Keeping valid tool_result with ID: {tool_result_id}"
                                    )
                            valid_content.append(content_block)
                        message["content"] = valid_content
                        print(
                            f"DEBUG: Removed {removed_count} orphaned tool_results. Content blocks: {original_count} -> {len(valid_content)}"
                        )

    def __call__(self, content, stream_callback=None):
        """Main call method with optional streaming support."""
        print(f"DEBUG: LLM.__call__ received content with {len(content)} items:")
        for i, item in enumerate(content):
            item_type = (
                item.get("type")
                if isinstance(item, dict)
                else getattr(item, "type", "unknown")
            )
            print(f"DEBUG:   Item {i}: {item_type}")
            if item_type == "tool_result":
                tool_use_id = (
                    item.get("tool_use_id")
                    if isinstance(item, dict)
                    else getattr(item, "tool_use_id", "unknown")
                )
                print(f"DEBUG:     tool_use_id: {tool_use_id}")

        self.messages.append({"role": "user", "content": content})

        # Add cache control to the last content item if it exists
        user_message = self.messages[-1]
        if user_message.get("content") and len(user_message["content"]) > 0:
            user_message["content"][-1]["cache_control"] = {"type": "ephemeral"}

        # Note: Message validation is moved to after tool execution to prevent interference
        # with active tool calls that haven't received results yet

        try:
            # Use streaming if callback provided
            if stream_callback:
                # Get response from streaming
                response_text, tool_calls = self._call_with_streaming(stream_callback)

                # Build assistant message for streaming response
                assistant_response = {"role": "assistant", "content": []}

                # Add text content if any
                if response_text:
                    assistant_response["content"].append(
                        {"type": "text", "text": response_text}
                    )

                # Add tool_use blocks
                for tool_call in tool_calls:
                    # Create a proper tool_use content block as a dict
                    tool_use_block = {
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["name"],
                        "input": tool_call["input"],
                    }
                    assistant_response["content"].append(tool_use_block)

                # Append assistant message to conversation history
                print(
                    f"DEBUG: Appending streaming assistant response. Messages before: {len(self.messages)}"
                )
                self.messages.append(assistant_response)
                print(f"DEBUG: Messages after: {len(self.messages)}")

                # Clean up cache control from user message
                self._remove_cache_control()

                # Return the expected format
                return response_text, tool_calls
            else:
                response = self._call_anthropic()
        except (RateLimitError, APIError) as e:
            print(f"\nRate limit or API error occurred: {str(e)}")
            raise
        finally:
            # Clean up cache control safely
            self._remove_cache_control()

        # Track token usage
        if hasattr(response, "usage"):
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.total_tokens = self.total_input_tokens + self.total_output_tokens

            # Emit token usage update to web client
            try:
                from flask import session as flask_session

                session_id = flask_session.get("session_id")
                if session_id:
                    emit(
                        "token_usage_update",
                        {
                            "input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens,
                            "total_input_tokens": self.total_input_tokens,
                            "total_output_tokens": self.total_output_tokens,
                            "total_tokens": self.total_tokens,
                            "timestamp": datetime.now().isoformat(),
                        },
                        room=session_id,
                    )
            except:
                # Ignore if not in web context or Flask context unavailable
                pass

        assistant_response = {"role": "assistant", "content": []}
        tool_calls = []
        output_text = ""

        for content in response.content:
            if content.type == "text":
                text_content = content.text
                output_text += text_content
                assistant_response["content"].append(
                    {"type": "text", "text": text_content}
                )
                print(
                    f"DEBUG: Adding text content to assistant response: {len(text_content)} chars"
                )
            elif content.type == "tool_use":
                assistant_response["content"].append(content)
                tool_calls.append(
                    {"id": content.id, "name": content.name, "input": content.input}
                )
                print(
                    f"DEBUG: Adding tool_use to assistant response: {content.name} with ID: {content.id}"
                )

        print(
            f"DEBUG: Appending assistant response to messages. Total messages before: {len(self.messages)}"
        )
        print(
            f"DEBUG: Assistant response content blocks: {len(assistant_response['content'])}"
        )
        for i, content in enumerate(assistant_response["content"]):
            content_type = (
                content.get("type")
                if isinstance(content, dict)
                else getattr(content, "type", "unknown")
            )
            print(f"DEBUG:   Assistant content {i}: {content_type}")

        self.messages.append(assistant_response)
        print(
            f"DEBUG: Total messages after adding assistant response: {len(self.messages)}"
        )

        # Validate message structure after assistant response is added, but only if no tools were called
        # (tool results will be added later and we don't want to interfere)
        if not tool_calls:
            self._validate_message_structure(skip_active_tools=False)

        return output_text, tool_calls