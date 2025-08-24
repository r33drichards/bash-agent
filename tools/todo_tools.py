create_todo_tool = {
    "name": "create_todo",
    "description": "Create a new todo item for task tracking. Use this to break down complex work into manageable tasks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "A clear, concise title for the todo"
            },
            "description": {
                "type": "string",
                "description": "Detailed description of what needs to be done"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Priority level of the todo (default: medium)"
            },
            "project": {
                "type": "string",
                "description": "Project or category this todo belongs to"
            },
            "due_date": {
                "type": "string",
                "description": "Due date in YYYY-MM-DD format"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to categorize the todo"
            },
            "time_estimate": {
                "type": "integer",
                "description": "Estimated time in minutes to complete the task"
            }
        },
        "required": ["title"]
    }
}

update_todo_tool = {
    "name": "update_todo",
    "description": "Update an existing todo item. Use this to change state (todo/in_progress/completed), priority, or other details.",
    "input_schema": {
        "type": "object", 
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "The ID of the todo to update"
            },
            "title": {
                "type": "string",
                "description": "New title for the todo"
            },
            "description": {
                "type": "string",
                "description": "New description for the todo"
            },
            "state": {
                "type": "string",
                "enum": ["todo", "in_progress", "completed"],
                "description": "New state for the todo"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "New priority level"
            },
            "project": {
                "type": "string",
                "description": "New project assignment"
            },
            "due_date": {
                "type": "string",
                "description": "New due date in YYYY-MM-DD format"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New tags for the todo"
            },
            "time_estimate": {
                "type": "integer",
                "description": "New time estimate in minutes"
            }
        },
        "required": ["todo_id"]
    }
}

list_todos_tool = {
    "name": "list_todos",
    "description": "List todos with optional filtering by state, priority, or project. Use this to see current work status.",
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": ["todo", "in_progress", "completed"],
                "description": "Filter by state"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Filter by priority"
            },
            "project": {
                "type": "string",
                "description": "Filter by project"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of todos to return (default: 50)"
            }
        }
    }
}

get_kanban_board_tool = {
    "name": "get_kanban_board",
    "description": "Get a kanban board view of all todos organized by state (todo, in_progress, completed).",
    "input_schema": {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Optional project filter"
            }
        }
    }
}

search_todos_tool = {
    "name": "search_todos",
    "description": "Search todos by title or description text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to find todos"
            },
            "include_completed": {
                "type": "boolean",
                "description": "Whether to include completed todos in search (default: false)"
            }
        },
        "required": ["query"]
    }
}

get_todo_tool = {
    "name": "get_todo",
    "description": "Get detailed information about a specific todo by ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "The ID of the todo to retrieve"
            }
        },
        "required": ["todo_id"]
    }
}

delete_todo_tool = {
    "name": "delete_todo",
    "description": "Delete a todo by ID. Use sparingly - usually better to mark as completed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "The ID of the todo to delete"
            }
        },
        "required": ["todo_id"]
    }
}

get_todo_stats_tool = {
    "name": "get_todo_stats",
    "description": "Get statistics about todos (counts by state, priority, overdue items, etc.).",
    "input_schema": {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Optional project filter for stats"
            }
        }
    }
}