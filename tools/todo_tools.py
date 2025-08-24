def get_current_todo_manager():
    """Get the todo manager for the current session."""
    try:
        from agent.github_utils import get_current_todo_manager as get_todo_manager
        return get_todo_manager()
    except ImportError:
        # Fallback when not in Flask context
        from todos import TodoManager
        return TodoManager()

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

def create_todo(title, description="", priority="medium", project=None, due_date=None, tags=None, estimated_hours=None):
    """Create a new todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todo_id = todo_manager.create_todo(
            title=title,
            description=description,
            priority=priority,
            project=project,
            due_date=due_date,
            tags=tags or [],
            estimated_hours=estimated_hours
        )
        return f"Todo created successfully with ID: {todo_id}\nTitle: {title}\nPriority: {priority}"
    except Exception as e:
        return f"Error creating todo: {str(e)}"

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

def update_todo(todo_id, **kwargs):
    """Update a todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        success = todo_manager.update_todo(todo_id, **kwargs)
        
        if success:
            updated_fields = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"Todo {todo_id} updated successfully.\nUpdated: {updated_fields}"
        else:
            return f"Todo with ID {todo_id} not found or could not be updated."
    except Exception as e:
        return f"Error updating todo: {str(e)}"

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

def list_todos(state=None, priority=None, project=None, limit=20):
    """List todos using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todos = todo_manager.list_todos(
            state=state,
            priority=priority,
            project=project,
            limit=limit
        )
        
        if not todos:
            filter_desc = []
            if state: filter_desc.append(f"state={state}")
            if priority: filter_desc.append(f"priority={priority}")
            if project: filter_desc.append(f"project={project}")
            filters = f" ({', '.join(filter_desc)})" if filter_desc else ""
            return f"No todos found{filters}."
        
        result_lines = [f"Found {len(todos)} todos:"]
        for todo in todos:
            status_emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(todo['state'], "📋")
            priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
            
            result_lines.append(f"\n{status_emoji} {priority_emoji} [{todo['state'].upper()}] {todo['title']}")
            result_lines.append(f"   ID: {todo['id']}")
            
            if todo['description']:
                desc_preview = todo['description'][:100] + "..." if len(todo['description']) > 100 else todo['description']
                result_lines.append(f"   Description: {desc_preview}")
            
            if todo['project']:
                result_lines.append(f"   Project: {todo['project']}")
            
            if todo['due_date']:
                result_lines.append(f"   Due: {todo['due_date']}")
            
            result_lines.append(f"   Created: {todo['created_at']}")
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error listing todos: {str(e)}"

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

def search_todos(query, include_completed=False):
    """Search todos using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todos = todo_manager.search_todos(query, include_completed)
        
        if not todos:
            return f"No todos found matching '{query}'."
        
        result_lines = [f"Found {len(todos)} todos matching '{query}':"]
        for todo in todos:
            status_emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(todo['state'], "📋")
            priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
            
            result_lines.append(f"\n{status_emoji} {priority_emoji} {todo['title']}")
            result_lines.append(f"   ID: {todo['id']}")
            result_lines.append(f"   State: {todo['state']}")
            if todo['description']:
                desc_preview = todo['description'][:100] + "..." if len(todo['description']) > 100 else todo['description']
                result_lines.append(f"   Description: {desc_preview}")
            
        return "\n".join(result_lines)
    except ValueError as e:
        # Return the error as a tool result so the agent can recover
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching todos: {str(e)}"

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

def get_todo(todo_id):
    """Get a specific todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todo = todo_manager.get_todo(todo_id)
        
        if not todo:
            return f"Todo with ID {todo_id} not found."
        
        status_emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(todo['state'], "📋")
        priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
        
        result_lines = [
            f"{status_emoji} {priority_emoji} {todo['title']}",
            f"ID: {todo['id']}",
            f"State: {todo['state']}",
            f"Priority: {todo['priority']}"
        ]
        
        if todo['description']:
            result_lines.append(f"Description: {todo['description']}")
        
        if todo['project']:
            result_lines.append(f"Project: {todo['project']}")
        
        if todo['due_date']:
            result_lines.append(f"Due Date: {todo['due_date']}")
        
        if todo['tags']:
            result_lines.append(f"Tags: {', '.join(todo['tags'])}")
        
        if todo['estimated_hours']:
            result_lines.append(f"Estimated Hours: {todo['estimated_hours']}")
        
        if todo['actual_hours']:
            result_lines.append(f"Actual Hours: {todo['actual_hours']}")
        
        result_lines.extend([
            f"Created: {todo['created_at']}",
            f"Updated: {todo['updated_at']}"
        ])
        
        if todo['completed_at']:
            result_lines.append(f"Completed: {todo['completed_at']}")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving todo: {str(e)}"

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

def delete_todo(todo_id):
    """Delete a todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        success = todo_manager.delete_todo(todo_id)
        
        if success:
            return f"Todo with ID {todo_id} deleted successfully."
        else:
            return f"Todo with ID {todo_id} not found or could not be deleted."
    except Exception as e:
        return f"Error deleting todo: {str(e)}"

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

def get_todo_stats(project=None):
    """Get todo statistics using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        stats = todo_manager.get_project_stats(project)
        
        result_lines = ["=== TODO STATISTICS ==="]
        if project:
            result_lines[0] += f" (Project: {project})"
        
        # State counts
        result_lines.append("\n📊 By State:")
        for state, count in stats['states'].items():
            emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(state, "📋")
            result_lines.append(f"   {emoji} {state.replace('_', ' ').title()}: {count}")
        
        # Priority counts
        if stats['priorities']:
            result_lines.append("\n🎯 By Priority (active only):")
            for priority, count in stats['priorities'].items():
                emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(priority, "🟡")
                result_lines.append(f"   {emoji} {priority.title()}: {count}")
        
        # Overdue and total
        result_lines.append(f"\n⚠️  Overdue: {stats['overdue']}")
        result_lines.append(f"📈 Total: {stats['total']}")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error getting todo stats: {str(e)}"