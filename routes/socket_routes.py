import uuid
import threading
import asyncio
from datetime import datetime
from flask import session
from flask_socketio import emit, join_room, leave_room

from agent.session_manager import sessions
from agent.llm import LLM
from agent.mcp_client import get_mcp_client, initialize_mcp_client
from agent.message_handler import handle_user_message_processing
from agent.tool_execution import handle_tool_call_web, execute_tool_call_web
from agent.conversation import save_conversation_history, load_conversation_history
from agent.file_cleanup import cleanup_old_files
from memory import MemoryManager
from todos import TodoManager


def register_socket_events(socketio, app):
    """Register all socket events"""
    
    @socketio.on("connect")
    def handle_connect(auth=None):
        session_id = str(uuid.uuid4())
        join_room(session_id)
        session["session_id"] = session_id

        # Initialize session first (without LLM)
        sessions[session_id] = {
            "auto_confirm": app.config["AUTO_CONFIRM"],
            "connected_at": datetime.now(),
            "conversation_history": [],
            "memory_manager": MemoryManager(),
            "todo_manager": TodoManager(),
        }

        # Initialize global MCP client first if not already done
        mcp_client = get_mcp_client()
        if not mcp_client.is_initialized:
            working_dir = app.config.get("WORKING_DIR")
            mcp_config_path = app.config.get("MCP_CONFIG")
            
            # Import get_mcp_loop from tool_execution
            from agent.tool_execution import get_mcp_loop
            
            # Run MCP initialization in the dedicated MCP event loop
            mcp_loop = get_mcp_loop()
            future = asyncio.run_coroutine_threadsafe(
                initialize_mcp_client(mcp_config_path, socketio, working_dir),
                mcp_loop
            )
            
            # Wait for MCP initialization to complete before creating LLM
            try:
                # Wait up to 10 seconds for MCP initialization
                future.result(timeout=10)
                print(f"MCP initialization completed")
            except asyncio.TimeoutError:
                print(f"Warning: MCP initialization timed out, continuing without MCP tools")
            except Exception as e:
                print(f"Warning: MCP initialization failed: {e}")
        else:
            print(f"MCP client already initialized with {len(mcp_client.servers)} servers")

        # Now initialize LLM with the session context available (MCP tools will be included if available)
        sessions[session_id]["llm"] = LLM(
            "claude-3-7-sonnet-latest", session_id
        )

        emit("session_started", {"session_id": session_id})
        emit(
            "message",
            {
                "type": "system",
                "content": f"Connected to {app.config.get('TITLE', 'Claude Code Agent')}. Type your message to start... Initializing MCP servers...",
                "timestamp": datetime.now().isoformat(),
            },
        )

        # Send conversation history if available
        history = load_conversation_history()
        if history:
            emit("conversation_history", history)

    @socketio.on("disconnect")
    def handle_disconnect():
        session_id = session.get("session_id")
        if session_id in sessions:
            # Save conversation history before cleanup
            save_conversation_history(session_id)
            del sessions[session_id]
        leave_room(session_id)

    @socketio.on("user_message")
    def handle_user_message(data):
        session_id = session.get("session_id")
        if session_id not in sessions:
            emit("error", {"message": "Session not found"})
            return

        # Clean up old uploaded files periodically
        cleanup_old_files()

        # Delegate to the message handler
        handle_user_message_processing(data, session_id, socketio)

    @socketio.on("tool_confirm")
    def handle_tool_confirm(data):
        session_id = session.get("session_id")
        if session_id not in sessions:
            emit("error", {"message": "Session not found"})
            return

        confirmed = data.get("confirmed", False)

        if confirmed:
            # Execute the tool call
            tool_call = data.get("tool_call")
            if tool_call:
                execute_tool_call_web(tool_call, session_id, socketio)
        else:
            # Handle tool cancellation with proper tool_result
            tool_call = data.get("tool_call")
            rejection_reason = data.get("rejection_reason", "")

            if tool_call:
                # Create a tool_result for the cancelled tool
                cancellation_message = "Tool execution cancelled by user."
                if rejection_reason:
                    cancellation_message += f" Reason: {rejection_reason}"

                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": [{"type": "text", "text": f"Error: {cancellation_message}"}],
                }

                # Send cancellation message to user
                emit(
                    "message",
                    {
                        "type": "system",
                        "content": cancellation_message,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

                # Send tool_result back to LLM to continue conversation
                llm = sessions[session_id]["llm"]
                output, new_tool_calls = llm([tool_result])

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
                            new_tool_call, session_id, sessions[session_id]["auto_confirm"], socketio
                        )
            else:
                # Fallback if no tool_call data
                emit(
                    "message",
                    {
                        "type": "system",
                        "content": "Tool execution cancelled by user.",
                        "timestamp": datetime.now().isoformat(),
                    },
                )

    @socketio.on("update_auto_confirm")
    def handle_update_auto_confirm(data):
        session_id = session.get("session_id")
        if session_id not in sessions:
            emit("error", {"message": "Session not found"})
            return

        enabled = data.get("enabled", False)
        sessions[session_id]["auto_confirm"] = enabled

        # Send confirmation message
        status = "enabled" if enabled else "disabled"
        emit(
            "message",
            {
                "type": "system",
                "content": f"Auto-confirm {status}.",
                "timestamp": datetime.now().isoformat(),
            },
        )

    @socketio.on("get_auto_confirm_state")
    def handle_get_auto_confirm_state():
        session_id = session.get("session_id")
        if session_id not in sessions:
            emit("error", {"message": "Session not found"})
            return

        enabled = sessions[session_id]["auto_confirm"]
        emit("auto_confirm_state", {"enabled": enabled})