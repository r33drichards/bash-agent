import os

def get_current_session_id():
    """Get the current session ID from Flask session context"""
    try:
        from agent.github_utils import get_current_session_id as get_session_id
        return get_session_id()
    except ImportError:
        return None

def get_current_github_rag():
    """Get the current session's GitHub RAG instance."""
    try:
        from agent.github_utils import get_current_github_rag as get_github_rag
        return get_github_rag()
    except Exception as e:
        # Fallback when not in Flask context
        from github_rag import GitHubRAG
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not found")
        return GitHubRAG(openai_api_key)

def get_current_memory_manager():
    """Get the memory manager for the current session."""
    try:
        from agent.github_utils import get_current_memory_manager as get_memory_manager
        return get_memory_manager()
    except ImportError:
        # Fallback when not in Flask context
        from memory import MemoryManager
        return MemoryManager()

github_rag_index_tool = {
    "name": "github_rag_index",
    "description": "Index a GitHub repository for RAG (Retrieval Augmented Generation) queries. This tool clones the repository, processes its files, and creates a searchable vector database for code analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": "GitHub repository URL to clone and index (e.g., https://github.com/user/repo)"
            },
            "include_extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of file extensions to include (e.g., ['py', 'js', 'md']). If not specified, all text files are included."
            },
            "ignore_dirs": {
                "type": "array", 
                "items": {"type": "string"},
                "description": "Optional list of directories to ignore (e.g., ['node_modules', 'venv']). Default includes common ignore patterns."
            }
        },
        "required": ["repo_url"]
    }
}

def github_rag_index(repo_url, include_extensions=None, ignore_dirs=None):
    """Index a GitHub repository for RAG queries."""
    try:
        github_rag = get_current_github_rag()
        
        # Create progress callback that emits to web client
        def progress_callback(progress_data):
            session_id = get_current_session_id()
            if session_id:
                try:
                    from flask_socketio import emit
                    emit('rag_index_progress', progress_data, room=session_id)
                except ImportError:
                    pass  # Ignore if socketio not available
        
        result = github_rag.index_repository(
            repo_url=repo_url,
            include_extensions=include_extensions,
            ignore_dirs=ignore_dirs,
            progress_callback=progress_callback
        )
        
        if result['success']:
            # Add to memory for context
            try:
                memory_manager = get_current_memory_manager()
                memory_manager.save_memory(
                    title=f"GitHub Repository Indexed: {result['repo_name']}",
                    content=f"Repository: {repo_url}\nCollection: {result['collection_name']}\nDocuments: {result.get('document_count', 0)}\nChunks: {result.get('chunk_count', 0)}",
                    tags=['github_rag', 'repository', result['repo_name']]
                )
            except Exception:
                pass  # Ignore memory save errors
            
            # Refresh system prompt to include the new repository
            try:
                session_id = get_current_session_id()
                if session_id:
                    from agent.session_manager import sessions
                    if session_id in sessions:
                        llm = sessions[session_id]['llm']
                        llm.refresh_system_prompt()
            except Exception:
                pass  # Ignore refresh errors
            
            return f"✅ {result['message']}\n\nRepository: {result['repo_name']}\nCollection: {result['collection_name']}\nDocuments indexed: {result.get('document_count', 0)}\nChunks created: {result.get('chunk_count', 0)}\n\nYou can now query this repository using the github_rag_query tool with collection_name: {result['collection_name']}"
        else:
            return f"❌ Failed to index repository: {result['error']}"
            
    except Exception as e:
        return f"Error indexing repository: {str(e)}"

github_rag_query_tool = {
    "name": "github_rag_query",
    "description": "Query an indexed GitHub repository using RAG. Ask questions about the codebase and get answers with citations to specific files and code snippets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "collection_name": {
                "type": "string",
                "description": "The collection name of the indexed repository (returned by github_rag_index or shown in github_rag_list)"
            },
            "question": {
                "type": "string",
                "description": "The question to ask about the codebase"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of relevant code snippets to retrieve (default: 5)",
                "default": 5
            }
        },
        "required": ["collection_name", "question"]
    }
}

def github_rag_query(collection_name, question, max_results=5):
    """Query an indexed GitHub repository."""
    try:
        github_rag = get_current_github_rag()
        result = github_rag.query_repository(
            collection_name=collection_name,
            question=question,
            max_results=max_results
        )
        
        if result['success']:
            output_lines = [
                f"🔍 Query: {result['question']}",
                f"📁 Repository: {result['repository']}",
                f"📊 Sources found: {result['total_sources']}",
                "",
                "📝 Answer:",
                result['answer'],
                "",
                "📋 Citations:"
            ]
            
            for citation in result['citations']:
                output_lines.append(f"\n[{citation['source_id']}] {citation['file_path']}")
                output_lines.append(f"└─ {citation['snippet']}")
            
            return "\n".join(output_lines)
        else:
            return f"❌ Query failed: {result['error']}"
            
    except Exception as e:
        return f"Error querying repository: {str(e)}"

github_rag_list_tool = {
    "name": "github_rag_list",
    "description": "List all indexed GitHub repositories and their collection names for querying.",
    "input_schema": {
        "type": "object",
        "properties": {}
    }
}

def github_rag_list():
    """List all indexed GitHub repositories."""
    try:
        github_rag = get_current_github_rag()
        repositories = github_rag.list_repositories()
        
        if not repositories:
            return "📂 No GitHub repositories have been indexed yet.\n\nUse the github_rag_index tool to index a repository first."
        
        output_lines = ["📚 Indexed GitHub Repositories:", ""]
        
        for repo in repositories:
            output_lines.extend([
                f"📁 {repo['repo_name']}",
                f"   Collection: {repo['collection_name']}",
                f"   URL: {repo['repo_url']}",
                f"   Files: {repo['document_count']} | Chunks: {repo['chunk_count']}",
                ""
            ])
        
        output_lines.append("💡 Use github_rag_query with the collection name to ask questions about any repository.")
        
        return "\n".join(output_lines)
        
    except Exception as e:
        return f"Error listing repositories: {str(e)}"