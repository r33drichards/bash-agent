from datetime import datetime
from flask_socketio import emit

from .session_manager import sessions
from .utils import get_file_content_by_id


def handle_user_message_processing(data, session_id, socketio):
    """Handle the processing of user messages"""
    print(f"=== USER_MESSAGE EVENT RECEIVED ===")
    print(f"Raw data received: {data}")
    print(f"Session ID: {session_id}")

    if session_id not in sessions:
        print(f"ERROR: Session {session_id} not found in sessions")
        emit("error", {"message": "Session not found"})
        return

    user_input = data.get("message", "").strip()
    print(f"User input: '{user_input}'")

    if not user_input:
        print("ERROR: No user input provided")
        return

    # Get attached files and resolve content for LLM processing
    attached_files = data.get("files", [])
    print(f"Attached files received: {len(attached_files)} files")

    # Process files - resolve file_id references to actual content
    resolved_files = []
    for i, file_info in enumerate(attached_files):
        print(
            f"  File {i + 1}: {file_info.get('name', 'unknown')} - type: {file_info.get('type', 'unknown')}"
        )

        if "content" in file_info:
            # Small file with direct content
            resolved_files.append(file_info)
            print(f"    Direct content: {len(str(file_info.get('content', '')))} chars")
        elif "file_id" in file_info:
            # Large file stored with file_id - retrieve content
            file_data = get_file_content_by_id(file_info["file_id"])
            if "error" in file_data:
                print(f"    Error loading file: {file_data['error']}")
                # Add error info
                resolved_files.append(
                    {
                        "name": file_info["name"],
                        "content": f"[Error loading file: {file_data['error']}]",
                        "type": "error",
                    }
                )
            else:
                print(
                    f"    Retrieved content: {len(str(file_data.get('content', '')))} chars"
                )
                resolved_files.append(
                    {
                        "name": file_data["name"],
                        "content": file_data["content"],
                        "type": file_data["type"],
                    }
                )

    # Process files and generate summaries once
    llm_message = user_input
    display_message = user_input
    history_message = user_input

    print("Building messages...")
    if resolved_files:
        print(f"Processing {len(resolved_files)} resolved files")
        # Check session still exists before accessing LLM for file processing
        if session_id not in sessions:
            print(f"ERROR: Session {session_id} was removed before file processing")
            emit("error", {"message": "Session expired during file processing"})
            return
        llm = sessions[session_id]["llm"]

        for file_info in resolved_files:
            if file_info.get("type") == "image":
                print(f"  Summarizing image: {file_info['name']}")
                # Generate image summary once
                image_summary = llm.summarize_image(
                    file_info["content"], file_info["name"]
                )

                # Add to LLM message (for processing)
                llm_message += (
                    f"\n\n[Image Description for {file_info['name']}]:\n{image_summary}"
                )

                # Add to display message (clean reference)
                display_message += f"\n\n[Image: {file_info['name']}]"

                # Add to history message (with description)
                history_message += (
                    f"\n\n[Image: {file_info['name']}]\nDescription: {image_summary}"
                )
            else:
                print(f"  Adding file: {file_info['name']}")
                file_content = f"\n\n--- File: {file_info['name']} ---\n{file_info['content']}\n--- End of {file_info['name']} ---"

                # Add to all messages (same content for text files)
                llm_message += file_content
                display_message += file_content
                history_message += file_content

    # Echo user message (clean version for display)
    user_message_display = {
        "type": "user",
        "content": display_message,
        "timestamp": datetime.now().isoformat(),
    }
    print(f"Emitting user message: {user_message_display}")
    emit("message", user_message_display)

    # Store in conversation history (with descriptions)
    user_message_history = {
        "type": "user",
        "content": history_message,
        "timestamp": datetime.now().isoformat(),
    }

    # Double-check session still exists before accessing
    if session_id not in sessions:
        print(
            f"ERROR: Session {session_id} was removed before storing conversation history"
        )
        emit("error", {"message": "Session expired"})
        return

    sessions[session_id]["conversation_history"].append(user_message_history)
    print(f"Added message to conversation history")

    # Process with LLM
    print(f"Starting LLM processing...")
    try:
        # Double-check session still exists before accessing LLM components
        if session_id not in sessions:
            print(f"ERROR: Session {session_id} was removed before LLM processing")
            emit("error", {"message": "Session expired during processing"})
            return

        session_data = sessions[
            session_id
        ]  # Get session data once to avoid multiple lookups
        llm = session_data["llm"]
        auto_confirm = session_data["auto_confirm"]
        memory_manager = session_data["memory_manager"]
        print(
            f"Retrieved session components: llm={llm is not None}, auto_confirm={auto_confirm}"
        )

        # Load relevant memories as context
        relevant_memories = memory_manager.get_memory_context(
            user_input, max_memories=3
        )

        # Load active todos as context
        todo_manager = session_data["todo_manager"]
        active_todos_summary = todo_manager.get_active_todos_summary()

        # Load GitHub RAG repositories context
        github_rag_context = ""
        try:
            if "github_rag" in session_data:
                github_rag = session_data["github_rag"]
                github_rag_context = github_rag.get_repository_memory_context()
        except Exception:
            pass

        # Prepare message with context
        context_parts = []

        if relevant_memories != "No relevant memories found.":
            context_parts.append(relevant_memories)

        if active_todos_summary != "No active todos.":
            context_parts.append(active_todos_summary)

        if (
            github_rag_context
            and github_rag_context
            != "No GitHub repositories have been indexed for RAG queries."
        ):
            context_parts.append(github_rag_context)

        if context_parts:
            context_msg = (
                "\n\n".join(context_parts) + f"\n\n=== USER MESSAGE ===\n{llm_message}"
            )
            msg = [{"type": "text", "text": context_msg}]
        else:
            msg = [{"type": "text", "text": llm_message}]

        print(
            f"Final message to LLM: {msg[0]['text'][:200]}..."
            if len(msg[0]["text"]) > 200
            else f"Final message to LLM: {msg[0]['text']}"
        )
        print("Calling LLM with streaming...")

        # Define streaming callback
        def stream_callback(chunk, stream_type):
            emit(
                "message_chunk",
                {
                    "type": "agent",
                    "chunk": chunk,
                    "stream_type": stream_type,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        # Call LLM with streaming
        output, tool_calls = llm(msg, stream_callback=stream_callback)
        print(
            f"LLM response received: {len(output)} chars, {len(tool_calls) if tool_calls else 0} tool calls"
        )

        # Send final agent response (for history)
        agent_message = {
            "type": "agent",
            "content": output,
            "timestamp": datetime.now().isoformat(),
        }
        emit("message_complete", agent_message)

        # Store in conversation history - check session still exists
        if session_id in sessions:
            sessions[session_id]["conversation_history"].append(agent_message)
        else:
            print(
                f"ERROR: Session {session_id} was removed before storing agent response"
            )

        # Handle tool calls
        if tool_calls:
            from .tool_execution import handle_tool_call_web
            for tool_call in tool_calls:
                handle_tool_call_web(tool_call, session_id, auto_confirm)

    except Exception as e:
        emit(
            "message",
            {
                "type": "error",
                "content": f"Error: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            },
        )