import asyncio
import traceback
import threading
from datetime import datetime

from flask_socketio import emit

from tools.bash_tool import execute_bash
from tools.sqlite_tool import execute_sqlite
from tools.ipython_tool import execute_ipython
from tools.todo_tools import (
    create_todo,
    update_todo,
    list_todos,
    search_todos,
    get_todo,
    delete_todo,
    get_todo_stats,
)
from tools.github_rag_tools import (
    github_rag_index,
    github_rag_query,
    github_rag_list,
)

from .session_manager import sessions
from .mcp_client import get_mcp_client

# Global MCP event loop
_mcp_loop = None
_mcp_thread = None

def get_mcp_loop():
    """Get or create the MCP event loop"""
    global _mcp_loop, _mcp_thread
    
    if _mcp_loop is None or not _mcp_loop.is_running():
        # Create a new event loop in a separate thread
        _mcp_loop = asyncio.new_event_loop()
        
        def run_loop():
            asyncio.set_event_loop(_mcp_loop)
            _mcp_loop.run_forever()
        
        _mcp_thread = threading.Thread(target=run_loop, daemon=True)
        _mcp_thread.start()
        
        # Give the loop a moment to start
        import time
        time.sleep(0.1)
    
    return _mcp_loop


def handle_tool_call_web(tool_call, session_id, auto_confirm, socketio_instance=None):
    """Handle tool call in web context"""
    if auto_confirm:
        execute_tool_call_web(tool_call, session_id, socketio_instance)
    else:
        # Send confirmation request
        emit(
            "tool_confirmation",
            {
                "tool_call_id": tool_call["id"],
                "tool_name": tool_call["name"],
                "tool_input": tool_call["input"],
                "tool_call": tool_call,
            },
            room=session_id,
        )


def execute_tool_call_web(tool_call, session_id, socketio_instance=None):
    """Execute tool call and emit results"""
    try:
        print(f"DEBUG: execute_tool_call_web received tool_call: {tool_call}")
        print(
            f"DEBUG: tool_call type: {type(tool_call)}, name: {tool_call.get('name')}, input: {tool_call.get('input')}"
        )

        # Send detailed tool execution info
        tool_info = {
            "type": "tool_execution",
            "tool_name": tool_call["name"],
            "tool_input": tool_call.get("input", {}),
            "timestamp": datetime.now().isoformat(),
        }

        # Add the actual code/command being executed
        tool_input = tool_call.get("input", {})
        if tool_call["name"] == "bash":
            tool_info["code"] = tool_input.get("command", "No command provided")
            tool_info["language"] = "bash"
            tool_info["timeout"] = tool_input.get("timeout", 30)
            tool_info["stream_output"] = tool_input.get("stream_output", False)
        elif tool_call["name"] == "ipython":
            tool_info["code"] = tool_input.get("code", "No code provided")
            tool_info["language"] = "python"
        elif tool_call["name"] == "sqlite":
            tool_info["code"] = tool_input.get("query", "No query provided")
            tool_info["language"] = "sql"

        emit("tool_execution_start", tool_info, room=session_id)

        # Check if this is an MCP tool and handle async execution
        is_mcp_tool = False
        try:
            mcp_client = get_mcp_client()
            if mcp_client and hasattr(mcp_client, "available_tools"):
                # Check if tool name matches any MCP tool
                is_mcp_tool = any(
                    tool["name"] == tool_call["name"]
                    for tool in mcp_client.available_tools
                )
                print(
                    f"DEBUG: Tool '{tool_call['name']}' - MCP tool check: {is_mcp_tool}"
                )
        except Exception:
            # Silently ignore errors to avoid breaking tool execution
            pass

        if is_mcp_tool:
            # MCP client is available, try to call the tool synchronously
            try:
                # Get MCP client and call tool directly
                mcp_client = get_mcp_client()
                
                # Run MCP tool call in the dedicated MCP event loop
                mcp_loop = get_mcp_loop()
                future = asyncio.run_coroutine_threadsafe(
                    mcp_client.call_tool(tool_call["name"], tool_call["input"]),
                    mcp_loop
                )
                mcp_result = future.result()  # This blocks until the coroutine completes
                
                if mcp_result.get("error"):
                    result_text = mcp_result["error"]
                else:
                    content = mcp_result.get("content", "No result returned")
                    # Handle different content types from MCP
                    if isinstance(content, list) and content:
                        # Check if content contains image data
                        has_image = False
                        image_data = None
                        text_content = ""
                        
                        for item in content:
                            # Handle different item formats
                            if hasattr(item, '__class__') and 'ImageContent' in str(item.__class__):
                                # MCP ImageContent object
                                has_image = True
                                if hasattr(item, 'data'):
                                    image_data = item.data
                                elif hasattr(item, 'source') and hasattr(item.source, 'data'):
                                    image_data = item.source.data
                                    
                            elif isinstance(item, dict):
                                if item.get('type') == 'image':
                                    has_image = True
                                    if 'data' in item:
                                        image_data = item['data']
                                    elif 'source' in item and 'data' in item['source']:
                                        image_data = item['source']['data']
                                elif item.get('type') == 'text':
                                    text_content += item.get('text', '')
                            elif hasattr(item, 'text'):
                                text_content = item.text
                        
                        # If we found an image, summarize it
                        if has_image and image_data:
                            # Get the LLM instance to access the summarize_image method
                            llm = sessions[session_id]["llm"]
                            if hasattr(llm, 'summarize_image'):
                                # Get the tool name for filename
                                filename = f"{tool_call['name']}_screenshot.png"
                                summary = llm.summarize_image(image_data, filename)
                                result_text = f"[Screenshot captured]\n\n{summary}"
                                if text_content:
                                    result_text = f"{text_content}\n\n{result_text}"
                                
                                # Display image to user (not included in LLM history)
                                if socketio_instance:
                                    socketio_instance.emit("screenshot_display", {
                                        "type": "image",
                                        "data": image_data,
                                        "filename": filename,
                                        "timestamp": datetime.now().isoformat()
                                    }, room=session_id)
                            else:
                                result_text = "[Screenshot captured - image data received but summarization not available]"
                        else:
                            # No image, handle as before
                            if hasattr(content[0], 'text'):
                                result_text = content[0].text
                            elif isinstance(content[0], dict) and 'text' in content[0]:
                                result_text = content[0]['text']
                            else:
                                result_text = str(content)
                    else:
                        result_text = str(content)

                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": [
                        {
                            "type": "text",
                            "text": result_text,
                        }
                    ],
                }
                
                # Also emit the result for the frontend
                if socketio_instance:
                    socketio_instance.emit(
                        "tool_result",
                        {
                            "tool_use_id": tool_call["id"],
                            "result": result_text,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )
                    
            except Exception as e:
                error_msg = f"Error executing MCP tool: {str(e)}"
                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": [
                        {
                            "type": "text",
                            "text": error_msg,
                        }
                    ],
                }
                
                # Also emit the error for the frontend
                if socketio_instance:
                    socketio_instance.emit(
                        "tool_result",
                        {
                            "tool_use_id": tool_call["id"],
                            "result": error_msg,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )
        else:
            # Execute the tool normally
            print(
                f"DEBUG: Executing standard tool: {tool_call['name']} with input: {tool_call.get('input')}"
            )
            result = execute_tool_call(tool_call)

        # Extract the result content
        result_content = ""
        plots = []
        if result and "content" in result and result["content"]:
            result_content = (
                result["content"][0]["text"]
                if result["content"][0]["type"] == "text"
                else str(result["content"])
            )

        # Extract plots if available (from IPython execution)
        if result and "plots" in result:
            plots = result["plots"]

        # Send detailed execution result
        result_data = {
            "type": "tool_result",
            "tool_name": tool_call["name"],
            "result": result_content,
            "timestamp": datetime.now().isoformat(),
        }

        if plots:
            result_data["plots"] = plots

        emit("tool_execution_result", result_data, room=session_id)

        # Send result back to LLM
        llm = sessions[session_id]["llm"]
        output, new_tool_calls = llm([result])

        # Validate message structure after tool result processing
        if hasattr(llm, "_validate_message_structure"):
            llm._validate_message_structure(skip_active_tools=False)

        # Send agent response
        agent_message = {
            "type": "agent",
            "content": output,
            "timestamp": datetime.now().isoformat(),
        }
        emit("message", agent_message, room=session_id)

        # Store in conversation history
        sessions[session_id]["conversation_history"].append(agent_message)

        # Handle any new tool calls
        if new_tool_calls:
            for new_tool_call in new_tool_calls:
                handle_tool_call_web(
                    new_tool_call, session_id, sessions[session_id]["auto_confirm"], socketio_instance
                )

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"ERROR: Tool execution failed: {str(e)}")
        print(f"ERROR: Full traceback:\n{error_details}")
        emit(
            "message",
            {
                "type": "error",
                "content": f"Tool execution error: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            },
            room=session_id,
        )


def execute_tool_call(tool_call):
    """Execute a tool call and return the result"""
    print(
        f"DEBUG: execute_tool_call received: name={tool_call.get('name')}, input={tool_call.get('input')}"
    )
    if tool_call["name"] == "bash":
        # Add better error handling for input format
        tool_input = tool_call.get("input", {})
        if not isinstance(tool_input, dict):
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text=f"Error: Tool input must be a dictionary, got {type(tool_input)}",
                    )
                ],
            )

        command = tool_input.get("command")
        if not command:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'command' parameter is required for bash tool",
                    )
                ],
            )

        timeout = tool_input.get("timeout", 30)
        stream_output = tool_input.get("stream_output", False)
        output_text = execute_bash(command, timeout, stream_output)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "sqlite":
        tool_input = tool_call.get("input", {})
        db_path = tool_input.get("db_path")
        query = tool_input.get("query")
        if not db_path:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'db_path' parameter is required for sqlite tool",
                    )
                ],
            )
        if not query:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'query' parameter is required for sqlite tool",
                    )
                ],
            )
        output_json = tool_input.get("output_json")
        print_result = tool_input.get("print_result", False)
        output_text = execute_sqlite(db_path, query, output_json, print_result)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "ipython":
        tool_input = tool_call.get("input", {})
        code = tool_input.get("code")
        if not code:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'code' parameter is required for ipython tool",
                    )
                ],
            )
        print_result = tool_input.get("print_result", False)
        output_text, plots = execute_ipython(code, print_result)
        result = dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
        return result

    elif tool_call["name"] == "create_todo":
        tool_input = tool_call.get("input", {})
        title = tool_input.get("title")
        if not title:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'title' parameter is required for create_todo tool",
                    )
                ],
            )
        description = tool_input.get("description", "")
        priority = tool_input.get("priority", "medium")
        project = tool_input.get("project")
        due_date = tool_input.get("due_date")
        tags = tool_input.get("tags")
        estimated_hours = tool_input.get("estimated_hours")
        output_text = create_todo(
            title, description, priority, project, due_date, tags, estimated_hours
        )
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "update_todo":
        tool_input = tool_call.get("input", {})
        todo_id = tool_input.get("todo_id")
        if not todo_id:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'todo_id' parameter is required for update_todo tool",
                    )
                ],
            )
        updates = {k: v for k, v in tool_input.items() if k != "todo_id"}
        output_text = update_todo(todo_id, **updates)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "list_todos":
        state = tool_call["input"].get("state")
        priority = tool_call["input"].get("priority")
        project = tool_call["input"].get("project")
        limit = tool_call["input"].get("limit", 20)
        output_text = list_todos(state, priority, project, limit)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )

    elif tool_call["name"] == "search_todos":
        tool_input = tool_call.get("input", {})
        query = tool_input.get("query")
        if not query:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'query' parameter is required for search_todos tool",
                    )
                ],
            )
        include_completed = tool_input.get("include_completed", False)
        output_text = search_todos(query, include_completed)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "get_todo":
        tool_input = tool_call.get("input", {})
        todo_id = tool_input.get("todo_id")
        if not todo_id:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'todo_id' parameter is required for get_todo tool",
                    )
                ],
            )
        output_text = get_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "delete_todo":
        tool_input = tool_call.get("input", {})
        todo_id = tool_input.get("todo_id")
        if not todo_id:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'todo_id' parameter is required for delete_todo tool",
                    )
                ],
            )
        output_text = delete_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "get_todo_stats":
        project = tool_call["input"].get("project")
        output_text = get_todo_stats(project)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_index":
        tool_input = tool_call.get("input", {})
        repo_url = tool_input.get("repo_url")
        if not repo_url:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'repo_url' parameter is required for github_rag_index tool",
                    )
                ],
            )
        include_extensions = tool_input.get("include_extensions")
        ignore_dirs = tool_input.get("ignore_dirs")
        output_text = github_rag_index(repo_url, include_extensions, ignore_dirs)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_query":
        tool_input = tool_call.get("input", {})
        collection_name = tool_input.get("collection_name")
        question = tool_input.get("question")
        if not collection_name:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'collection_name' parameter is required for github_rag_query tool",
                    )
                ],
            )
        if not question:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'question' parameter is required for github_rag_query tool",
                    )
                ],
            )
        max_results = tool_input.get("max_results", 5)
        output_text = github_rag_query(collection_name, question, max_results)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_list":
        output_text = github_rag_list()
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    else:
        # For now, just return an error for unsupported tools
        # MCP tools should be handled through the web interface with proper async support
        raise Exception(f"Unsupported tool: {tool_call['name']}")