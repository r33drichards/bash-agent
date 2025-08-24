import os
from flask import session as flask_session

from github_rag import GitHubRAG
from .session_manager import sessions


def get_current_session_id():
    """Get the current session ID from Flask session context"""
    return flask_session.get("session_id")


def get_current_todo_manager():
    """Get the todo manager for the current session."""
    session_id = flask_session.get("session_id")
    if session_id and session_id in sessions:
        return sessions[session_id]["todo_manager"]
    from todos import TodoManager
    return TodoManager()  # Fallback to default


def get_current_memory_manager():
    """Get the memory manager for the current session."""
    session_id = flask_session.get("session_id")
    if session_id and session_id in sessions:
        return sessions[session_id]["memory_manager"]
    from memory import MemoryManager
    return MemoryManager()  # Fallback to default


def get_current_github_rag():
    """Get the current session's GitHub RAG instance."""
    try:
        session_id = flask_session.get("session_id")
        if session_id and session_id in sessions:
            if "github_rag" not in sessions[session_id]:
                # Initialize GitHub RAG with OpenAI API key
                openai_api_key = os.environ.get("OPENAI_API_KEY")
                if not openai_api_key:
                    raise ValueError("OPENAI_API_KEY environment variable not found")
                sessions[session_id]["github_rag"] = GitHubRAG(openai_api_key)
            return sessions[session_id]["github_rag"]
        else:
            raise Exception("No active session found")
    except Exception as e:
        raise Exception(f"Could not get GitHub RAG instance: {str(e)}")


def github_rag_index(repo_url, include_extensions=None, ignore_dirs=None):
    """Index a GitHub repository for RAG queries."""
    try:
        github_rag = get_current_github_rag()

        # Create progress callback that emits to web client
        def progress_callback(progress_data):
            session_id = get_current_session_id()
            if session_id:
                from flask_socketio import SocketIO
                socketio = SocketIO()
                socketio.emit("rag_index_progress", progress_data, room=session_id)

        result = github_rag.index_repository(
            repo_url=repo_url,
            include_extensions=include_extensions,
            ignore_dirs=ignore_dirs,
            progress_callback=progress_callback,
        )

        if result["success"]:
            # Add to memory for context
            memory_manager = get_current_memory_manager()
            memory_manager.save_memory(
                title=f"GitHub Repository Indexed: {result['repo_name']}",
                content=f"Repository: {repo_url}\nCollection: {result['collection_name']}\nDocuments: {result.get('document_count', 0)}\nChunks: {result.get('chunk_count', 0)}",
                tags=["github_rag", "repository", result["repo_name"]],
            )

            # Refresh system prompt to include the new repository
            session_id = get_current_session_id()
            if session_id and session_id in sessions:
                llm = sessions[session_id]["llm"]
                llm.refresh_system_prompt()

            return f"✅ {result['message']}\n\nRepository: {result['repo_name']}\nCollection: {result['collection_name']}\nDocuments indexed: {result.get('document_count', 0)}\nChunks created: {result.get('chunk_count', 0)}\n\nYou can now query this repository using the github_rag_query tool with collection_name: {result['collection_name']}"
        else:
            return f"❌ Failed to index repository: {result['error']}"

    except Exception as e:
        return f"Error indexing repository: {str(e)}"


def github_rag_query(collection_name, question, max_results=5):
    """Query an indexed GitHub repository."""
    try:
        github_rag = get_current_github_rag()
        result = github_rag.query_repository(
            collection_name=collection_name, question=question, max_results=max_results
        )

        if result["success"]:
            output_lines = [
                f"🔍 Query: {result['question']}",
                f"📁 Repository: {result['repository']}",
                f"📊 Sources found: {result['total_sources']}",
                "",
                "📝 Answer:",
                result["answer"],
                "",
                "📋 Citations:",
            ]

            for citation in result["citations"]:
                output_lines.append(
                    f"\n[{citation['source_id']}] {citation['file_path']}"
                )
                output_lines.append(f"└─ {citation['snippet']}")

            return "\n".join(output_lines)
        else:
            return f"❌ Query failed: {result['error']}"

    except Exception as e:
        return f"Error querying repository: {str(e)}"


def github_rag_list():
    """List all indexed GitHub repositories."""
    try:
        github_rag = get_current_github_rag()
        repositories = github_rag.list_repositories()

        if not repositories:
            return "📂 No GitHub repositories have been indexed yet.\n\nUse the github_rag_index tool to index a repository first."

        output_lines = ["📚 Indexed GitHub Repositories:", ""]

        for repo in repositories:
            output_lines.extend(
                [
                    f"📁 {repo['repo_name']}",
                    f"   Collection: {repo['collection_name']}",
                    f"   URL: {repo['repo_url']}",
                    f"   Files: {repo['document_count']} | Chunks: {repo['chunk_count']}",
                    "",
                ]
            )

        output_lines.append(
            "💡 Use github_rag_query with the collection name to ask questions about any repository."
        )

        return "\n".join(output_lines)

    except Exception as e:
        return f"Error listing repositories: {str(e)}"


def emit_streaming_output(data, stream_type):
    """Emit streaming output to the web client if available."""
    try:
        from datetime import datetime
        from flask_socketio import emit
        
        session_id = flask_session.get("session_id")
        if session_id:
            emit(
                "streaming_output",
                {
                    "data": data,
                    "stream_type": stream_type,
                    "timestamp": datetime.now().isoformat(),
                },
                room=session_id,
            )
    except:
        pass  # Ignore if not in web context