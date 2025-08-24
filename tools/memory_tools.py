def get_current_memory_manager():
    """Get the memory manager for the current session."""
    try:
        from flask import session as flask_session
        from memory import MemoryManager
        session_id = flask_session.get('session_id')
        # This will need to be imported from the main module
        from agent import sessions
        if session_id and session_id in sessions:
            return sessions[session_id]['memory_manager']
        return MemoryManager()  # Fallback to default
    except ImportError:
        # Fallback when not in Flask context
        from memory import MemoryManager
        return MemoryManager()

save_memory_tool = {
    "name": "save_memory",
    "description": "Save information to memory for future reference. Use this to store important facts, solutions, or insights that might be useful later.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "A descriptive title for the memory"
            },
            "content": {
                "type": "string", 
                "description": "The content to store in memory"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to categorize the memory"
            }
        },
        "required": ["title", "content"]
    }
}

def save_memory(title, content, tags=None):
    """Save a memory using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memory_id = memory_manager.save_memory(title, content, tags or [])
        return f"Memory saved successfully with ID: {memory_id}\nTitle: {title}"
    except Exception as e:
        return f"Error saving memory: {str(e)}"

search_memory_tool = {
    "name": "search_memory",
    "description": "Search stored memories by content, title, or tags. Use this to recall previously stored information.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to find relevant memories"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to filter memories"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return (default: 10)"
            }
        }
    }
}

def search_memory(query=None, tags=None, limit=10):
    """Search memories using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memories = memory_manager.search_memories(query, tags, limit)
        
        if not memories:
            return "No memories found matching the search criteria."
        
        result_lines = [f"Found {len(memories)} memories:"]
        for memory in memories:
            result_lines.append(f"\nID: {memory['id']}")
            result_lines.append(f"Title: {memory['title']}")
            if memory['tags']:
                result_lines.append(f"Tags: {', '.join(memory['tags'])}")
            result_lines.append(f"Content: {memory['content']}")
            result_lines.append(f"Created: {memory['created_at']}")
            result_lines.append("---")
        
        return "\n".join(result_lines)
    except ValueError as e:
        # Return the error as a tool result so the agent can recover
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching memories: {str(e)}"

list_memories_tool = {
    "name": "list_memories",
    "description": "List all stored memories with optional pagination.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return (default: 20)"
            },
            "offset": {
                "type": "integer", 
                "description": "Number of memories to skip (default: 0)"
            }
        }
    }
}

def list_memories(limit=20, offset=0):
    """List memories using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memories = memory_manager.list_memories(limit, offset)
        
        if not memories:
            return "No memories found."
        
        result_lines = [f"Listing {len(memories)} memories (limit: {limit}, offset: {offset}):"]
        for memory in memories:
            result_lines.append(f"\nID: {memory['id']}")
            result_lines.append(f"Title: {memory['title']}")
            if memory['tags']:
                result_lines.append(f"Tags: {', '.join(memory['tags'])}")
            # Truncate content for list view
            content_preview = memory['content'][:100] + "..." if len(memory['content']) > 100 else memory['content']
            result_lines.append(f"Content: {content_preview}")
            result_lines.append(f"Created: {memory['created_at']}")
            result_lines.append("---")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error listing memories: {str(e)}"

get_memory_tool = {
    "name": "get_memory",
    "description": "Retrieve a specific memory by its ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The ID of the memory to retrieve"
            }
        },
        "required": ["memory_id"]
    }
}

def get_memory(memory_id):
    """Get a specific memory using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memory = memory_manager.get_memory(memory_id)
        
        if not memory:
            return f"Memory with ID {memory_id} not found."
        
        result_lines = [
            f"Memory ID: {memory['id']}",
            f"Title: {memory['title']}",
            f"Content: {memory['content']}"
        ]
        
        if memory['tags']:
            result_lines.append(f"Tags: {', '.join(memory['tags'])}")
        
        result_lines.extend([
            f"Created: {memory['created_at']}",
            f"Updated: {memory['updated_at']}",
            f"Last Accessed: {memory['accessed_at']}"
        ])
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving memory: {str(e)}"

delete_memory_tool = {
    "name": "delete_memory",
    "description": "Delete a memory by its ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The ID of the memory to delete"
            }
        },
        "required": ["memory_id"]
    }
}

def delete_memory(memory_id):
    """Delete a memory using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        success = memory_manager.delete_memory(memory_id)
        
        if success:
            return f"Memory with ID {memory_id} deleted successfully."
        else:
            return f"Memory with ID {memory_id} not found or could not be deleted."
    except Exception as e:
        return f"Error deleting memory: {str(e)}"