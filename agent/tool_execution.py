import threading
import asyncio
import traceback
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
from .mcp_client import handle_mcp_tool_call


def handle_tool_call_web(tool_call, session_id, auto_confirm):
    """Handle tool call in web context"""
    if auto_confirm:
        execute_tool_call_web(tool_call, session_id)
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


def execute_tool_call_web(tool_call, session_id):
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
        if session_id in sessions:
            session_data = sessions[session_id]
            mcp_client = session_data.get("mcp_client")
            if mcp_client and hasattr(mcp_client, "available_tools"):
                # Check if tool name matches any MCP tool
                is_mcp_tool = any(
                    tool["name"] == tool_call["name"]
                    for tool in mcp_client.available_tools
                )
                print(
                    f"DEBUG: Tool '{tool_call['name']}' - MCP tool check: {is_mcp_tool}"
                )

        if is_mcp_tool and session_id in sessions:
            session_data = sessions[session_id]
            if session_data.get("mcp_client"):
                # Initialize MCP client if not done yet
                if not session_data.get("mcp_initialized"):
                    result = {
                        "type": "tool_result",
                        "tool_use_id": tool_call["id"],
                        "content": [
                            {
                                "type": "text",
                                "text": "MCP client is still initializing. Please try again in a moment.",
                            }
                        ],
                    }
                else:
                    # MCP client is initialized, try to call the tool asynchronously
                    try:

                        def run_mcp_tool():
                            asyncio.run(handle_mcp_tool_call(session_id, tool_call))

                        # Run MCP tool call in a separate thread
                        mcp_tool_thread = threading.Thread(
                            target=run_mcp_tool, daemon=True
                        )
                        mcp_tool_thread.start()

                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": [
                                {
                                    "type": "text",
                                    "text": "MCP tool executed. Results will be emitted separately.",
                                }
                            ],
                        }
                    except Exception as e:
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Error executing MCP tool: {str(e)}",
                                }
                            ],
                        }
            else:
                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": [{"type": "text", "text": "MCP client not configured"}],
                }
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
                    new_tool_call, session_id, sessions[session_id]["auto_confirm"]
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
        db_path = tool_call["input"]["db_path"]
        query = tool_call["input"]["query"]
        output_json = tool_call["input"].get("output_json")
        print_result = tool_call["input"].get("print_result", False)
        output_text = execute_sqlite(db_path, query, output_json, print_result)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "ipython":
        code = tool_call["input"]["code"]
        print_result = tool_call["input"].get("print_result", False)
        output_text, plots = execute_ipython(code, print_result)
        result = dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
        return result

    elif tool_call["name"] == "create_todo":
        title = tool_call["input"]["title"]
        description = tool_call["input"].get("description", "")
        priority = tool_call["input"].get("priority", "medium")
        project = tool_call["input"].get("project")
        due_date = tool_call["input"].get("due_date")
        tags = tool_call["input"].get("tags")
        estimated_hours = tool_call["input"].get("estimated_hours")
        output_text = create_todo(
            title, description, priority, project, due_date, tags, estimated_hours
        )
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "update_todo":
        todo_id = tool_call["input"]["todo_id"]
        updates = {k: v for k, v in tool_call["input"].items() if k != "todo_id"}
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
        query = tool_call["input"]["query"]
        include_completed = tool_call["input"].get("include_completed", False)
        output_text = search_todos(query, include_completed)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "get_todo":
        todo_id = tool_call["input"]["todo_id"]
        output_text = get_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "delete_todo":
        todo_id = tool_call["input"]["todo_id"]
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
        repo_url = tool_call["input"]["repo_url"]
        include_extensions = tool_call["input"].get("include_extensions")
        ignore_dirs = tool_call["input"].get("ignore_dirs")
        output_text = github_rag_index(repo_url, include_extensions, ignore_dirs)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_query":
        collection_name = tool_call["input"]["collection_name"]
        question = tool_call["input"]["question"]
        max_results = tool_call["input"].get("max_results", 5)
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