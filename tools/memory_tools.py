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