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
# Flask imports are conditionally imported where needed to avoid import errors

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
                # Check for duplicate tool names before adding
                existing_tool_names = {tool.get("name") for tool in self.tools}
                for tool in mcp_tools:
                    if tool.get("name") not in existing_tool_names:
                        self.tools.append(tool)
                        existing_tool_names.add(tool.get("name"))
                    else:
                        print(f"DEBUG: Skipping duplicate MCP tool: {tool.get('name')}")
        except Exception as e:
            # Silently ignore errors to avoid breaking initialization
            print(f"DEBUG: Error adding MCP tools: {e}")
            pass

    def _build_system_prompt(self):
        """Build the system prompt dynamically including RAG repository information."""
        base_prompt = "use sequential thinking to break down complex tasks into manageable todos and work through them one by one."

        # Add RAG repository information if available
        rag_info = self._get_rag_repositories_info()
        if rag_info:
            base_prompt += rag_info + "\n\n"

        # Add custom system prompt if configured
        try:
            from flask import current_app
            if "SYSTEM_PROMPT" in current_app.config and current_app.config["SYSTEM_PROMPT"]:
                base_prompt += current_app.config["SYSTEM_PROMPT"]
        except (RuntimeError, ImportError):
            # Working outside of application context or Flask not available, skip Flask config
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
            thinking={
                "type": "enabled",
                "budget_tokens": 10000
            },
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
        """Handle streaming responses with proper thinking block handling."""
        print("Starting streaming response...")

        content_blocks = []
        current_block = None
        input_tokens = 0
        output_tokens = 0

        try:
            with self._call_anthropic(stream=True) as stream:
                for event in stream:
                    if event.type == "message_start":
                        input_tokens = event.message.usage.input_tokens

                    elif event.type == "content_block_start":
                        # Start a new content block
                        current_block = {"type": event.content_block.type}
                        
                        if event.content_block.type == "thinking":
                            current_block["thinking"] = ""
                        elif event.content_block.type == "text":
                            current_block["text"] = ""
                        elif event.content_block.type == "tool_use":
                            current_block.update({
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": event.content_block.input
                            })

                    elif event.type == "content_block_delta":
                        if current_block and event.delta.type == "thinking_delta":
                            current_block["thinking"] += event.delta.thinking
                            # Stream thinking content to callback
                            if stream_callback:
                                stream_callback(event.delta.thinking, "thinking")
                        elif current_block and event.delta.type == "text_delta":
                            current_block["text"] += event.delta.text
                            # Stream regular content to callback
                            if stream_callback:
                                stream_callback(event.delta.text, "content")
                        elif event.delta.type == "signature_delta":
                            # Add signature to thinking block
                            if current_block and current_block.get("type") == "thinking":
                                current_block["signature"] = event.delta.signature

                    elif event.type == "content_block_stop":
                        # Finalize the current block and add it to content_blocks
                        if current_block:
                            content_blocks.append(current_block)
                            current_block = None

                    elif event.type == "message_delta":
                        if hasattr(event.delta, "stop_reason"):
                            print(f"Stream finished: {event.delta.stop_reason}")

                    elif event.type == "message_stop":
                        if hasattr(event, "usage") and event.usage:
                            output_tokens = event.usage.output_tokens

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
                from flask_socketio import emit

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
            except Exception:
                # Ignore if not in web context or Flask context unavailable
                pass

        return content_blocks

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
                        print("DEBUG: Removed cache_control from user message")
                break


            

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

        # Debug: Print current message history before adding new message
        print(f"DEBUG: Current message count before adding: {len(self.messages)}")
        if self.messages:
            last_msg = self.messages[-1]
            print(f"DEBUG: Last message role: {last_msg.get('role')}")
            if last_msg.get('role') == 'assistant' and isinstance(last_msg.get('content'), list) and last_msg['content']:
                first_content = last_msg['content'][0]
                if isinstance(first_content, dict):
                    print(f"DEBUG: Last assistant message first content type: {first_content.get('type')}")
                else:
                    print(f"DEBUG: Last assistant message first content type: {getattr(first_content, 'type', 'unknown')}")

        self.messages.append({"role": "user", "content": content})

        # Add cache control to the last content item if it exists
        user_message = self.messages[-1]
        if user_message.get("content") and len(user_message["content"]) > 0:
            user_message["content"][-1]["cache_control"] = {"type": "ephemeral"}

        # Debug: Print the current messages structure before API call
        print(f"DEBUG: About to send {len(self.messages)} messages to API")
        for i, msg in enumerate(self.messages):
            print(f"DEBUG: Message {i}: role={msg.get('role')}")
            if isinstance(msg.get('content'), list):
                for j, content in enumerate(msg['content']):
                    if isinstance(content, dict):
                        content_type = content.get('type')
                        print(f"DEBUG:   Content {j}: type={content_type}")
                        if content_type == 'thinking':
                            text_preview = content.get('text', '')[:50] + '...' if len(content.get('text', '')) > 50 else content.get('text', '')
                            print(f"DEBUG:     Thinking text preview: '{text_preview}'")

        # Note: Message validation is moved to after tool execution to prevent interference
        # with active tool calls that haven't received results yet

        # When thinking is enabled, we need to ensure conversation history compliance

        try:
            # Use streaming if callback provided
            if stream_callback:
                # Get content blocks from streaming
                content_blocks = self._call_with_streaming(stream_callback)

                # Build assistant message for streaming response
                assistant_response = {"role": "assistant", "content": content_blocks}

                # Append assistant message to conversation history
                print(
                    f"DEBUG: Appending streaming assistant response. Messages before: {len(self.messages)}"
                )
                self.messages.append(assistant_response)
                print(f"DEBUG: Messages after: {len(self.messages)}")

                # Clean up cache control from user message
                self._remove_cache_control()

                # Extract response text and tool calls for return format
                response_text = ""
                tool_calls = []
                
                for block in content_blocks:
                    if block.get("type") == "text":
                        response_text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id"),
                            "name": block.get("name"), 
                            "input": block.get("input")
                        })

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
                from flask_socketio import emit

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
            except Exception:
                # Ignore if not in web context or Flask context unavailable
                pass

        # Convert API response content blocks to dict format
        content_blocks = []
        tool_calls = []
        output_text = ""

        print(f"DEBUG: Processing response with {len(response.content)} content blocks")
        for idx, content in enumerate(response.content):
            print(f"DEBUG: Response content[{idx}] type: {content.type}")
            
            if content.type == "thinking":
                # Create thinking block dict with signature if present
                thinking_block = {"type": "thinking", "thinking": content.thinking}
                if hasattr(content, 'signature') and content.signature:
                    thinking_block["signature"] = content.signature
                content_blocks.append(thinking_block)
                print(f"DEBUG: Added thinking block: {len(content.thinking)} chars")
                
            elif content.type == "redacted_thinking":
                # Create redacted thinking block dict
                redacted_block = {"type": "redacted_thinking"}
                if hasattr(content, 'data') and content.data:
                    redacted_block["data"] = content.data
                content_blocks.append(redacted_block)
                print("DEBUG: Added redacted thinking block")
                
            elif content.type == "text":
                text_block = {"type": "text", "text": content.text}
                content_blocks.append(text_block)
                output_text += content.text
                print(f"DEBUG: Added text block: {len(content.text)} chars")
                
            elif content.type == "tool_use":
                tool_use_block = {
                    "type": "tool_use",
                    "id": content.id,
                    "name": content.name,
                    "input": content.input
                }
                content_blocks.append(tool_use_block)
                tool_calls.append({
                    "id": content.id,
                    "name": content.name, 
                    "input": content.input
                })
                print(f"DEBUG: Added tool_use block: {content.name}")

        # Create assistant message with converted content blocks
        assistant_response = {"role": "assistant", "content": content_blocks}

        print(f"DEBUG: Appending assistant response with {len(content_blocks)} blocks")
        self.messages.append(assistant_response)
        print(f"DEBUG: Total messages after: {len(self.messages)}")

        return output_text, tool_calls