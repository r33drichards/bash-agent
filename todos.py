import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
import os

class TodoManager:
    """Manages persistent todo/task tracking with kanban board functionality."""
    
    # Kanban states
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    
    # Priority levels
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
    
    VALID_STATES = [TODO, IN_PROGRESS, COMPLETED]
    VALID_PRIORITIES = [LOW, MEDIUM, HIGH, URGENT]
    
    def __init__(self, db_path: str = "meta/todos.db"):
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
    
    def _init_database(self):
        """Initialize the todos database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create todos table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    state TEXT NOT NULL DEFAULT 'todo',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    tags TEXT,
                    metadata TEXT,
                    due_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    project TEXT,
                    assignee TEXT,
                    estimated_hours REAL,
                    actual_hours REAL
                )
            """)
            
            # Create indexes for faster queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_state ON todos(state)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos(priority)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos(due_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_created_at ON todos(created_at)")
            
            conn.commit()
    
    def create_todo(self, title: str, description: str = "", state: str = TODO, 
                   priority: str = MEDIUM, tags: List[str] = None, 
                   due_date: str = None, project: str = None, 
                   assignee: str = None, estimated_hours: float = None,
                   metadata: Dict[str, Any] = None) -> str:
        """Create a new todo and return its ID."""
        if state not in self.VALID_STATES:
            raise ValueError(f"Invalid state: {state}. Must be one of {self.VALID_STATES}")
        if priority not in self.VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {priority}. Must be one of {self.VALID_PRIORITIES}")
        
        todo_id = str(uuid.uuid4())
        tags_str = json.dumps(tags) if tags else "[]"
        metadata_str = json.dumps(metadata) if metadata else "{}"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO todos (id, title, description, state, priority, tags, 
                                 due_date, project, assignee, estimated_hours, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (todo_id, title, description, state, priority, tags_str, 
                  due_date, project, assignee, estimated_hours, metadata_str))
            conn.commit()
        
        return todo_id
    
    def get_todo(self, todo_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific todo by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, description, state, priority, tags, metadata, 
                       due_date, created_at, updated_at, completed_at, project, 
                       assignee, estimated_hours, actual_hours
                FROM todos WHERE id = ?
            """, (todo_id,))
            
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
        
        return None
    
    def update_todo(self, todo_id: str, **kwargs) -> bool:
        """Update an existing todo with any provided fields."""
        allowed_fields = {
            'title', 'description', 'state', 'priority', 'tags', 'due_date',
            'project', 'assignee', 'estimated_hours', 'actual_hours', 'metadata'
        }
        
        updates = []
        params = []
        
        for field, value in kwargs.items():
            if field not in allowed_fields:
                continue
                
            if field == 'state' and value not in self.VALID_STATES:
                raise ValueError(f"Invalid state: {value}")
            if field == 'priority' and value not in self.VALID_PRIORITIES:
                raise ValueError(f"Invalid priority: {value}")
            
            if field in ['tags', 'metadata'] and value is not None:
                value = json.dumps(value)
            
            updates.append(f"{field} = ?")
            params.append(value)
        
        if not updates:
            return False
        
        # Handle completion timestamp
        if 'state' in kwargs and kwargs['state'] == self.COMPLETED:
            updates.append("completed_at = CURRENT_TIMESTAMP")
        elif 'state' in kwargs and kwargs['state'] != self.COMPLETED:
            updates.append("completed_at = NULL")
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(todo_id)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            sql = f"UPDATE todos SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(sql, params)
            success = cursor.rowcount > 0
            conn.commit()
            return success
    
    def delete_todo(self, todo_id: str) -> bool:
        """Delete a todo by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
            success = cursor.rowcount > 0
            conn.commit()
            return success
    
    def list_todos(self, state: str = None, priority: str = None, 
                  project: str = None, limit: int = 50, offset: int = 0,
                  order_by: str = "created_at", ascending: bool = False) -> List[Dict[str, Any]]:
        """List todos with optional filtering and pagination."""
        where_conditions = []
        params = []
        
        if state:
            where_conditions.append("state = ?")
            params.append(state)
        
        if priority:
            where_conditions.append("priority = ?")
            params.append(priority)
        
        if project:
            where_conditions.append("project = ?")
            params.append(project)
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        order_direction = "ASC" if ascending else "DESC"
        
        sql = f"""
            SELECT id, title, description, state, priority, tags, metadata, 
                   due_date, created_at, updated_at, completed_at, project, 
                   assignee, estimated_hours, actual_hours
            FROM todos 
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def get_kanban_board(self, project: str = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get todos organized by kanban states."""
        board = {
            self.TODO: [],
            self.IN_PROGRESS: [],
            self.COMPLETED: []
        }
        
        for state in self.VALID_STATES:
            todos = self.list_todos(state=state, project=project, 
                                  order_by="priority DESC, created_at", limit=100)
            board[state] = todos
        
        return board
    
    def search_todos(self, query: str, include_completed: bool = False) -> List[Dict[str, Any]]:
        """Search todos by title or description."""
        # Validate query length and complexity
        MAX_QUERY_LENGTH = 10000
        if len(query) > MAX_QUERY_LENGTH:
            # Truncate the query and warn the user
            truncated_query = query[:MAX_QUERY_LENGTH]
            import warnings
            warnings.warn(f"Search query truncated from {len(query)} to {MAX_QUERY_LENGTH} characters")
            query = truncated_query
        
        where_conditions = ["(title LIKE ? OR description LIKE ?)"]
        params = [f"%{query}%", f"%{query}%"]
        
        if not include_completed:
            where_conditions.append("state != ?")
            params.append(self.COMPLETED)
        
        where_clause = " AND ".join(where_conditions)
        
        sql = f"""
            SELECT id, title, description, state, priority, tags, metadata, 
                   due_date, created_at, updated_at, completed_at, project, 
                   assignee, estimated_hours, actual_hours
            FROM todos 
            WHERE {where_clause}
            ORDER BY priority DESC, created_at DESC
        """
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError as e:
                if "LIKE or GLOB pattern too complex" in str(e):
                    # Fallback: try simplified search strategies
                    rows = self._fallback_todo_search(cursor, query, include_completed)
                else:
                    raise ValueError(f"Database search error: {str(e)}. Query: '{query}'")
            
            return [self._row_to_dict(row) for row in rows]
    
    def _fallback_todo_search(self, cursor, query: str, include_completed: bool = False):
        """Fallback search when LIKE pattern is too complex."""
        # Strategy 1: Try exact match first
        try:
            where_conditions = ["(title = ? OR description = ?)"]
            params = [query, query]
            
            if not include_completed:
                where_conditions.append("state != ?")
                params.append(self.COMPLETED)
            
            where_clause = " AND ".join(where_conditions)
            
            sql = f"""
                SELECT id, title, description, state, priority, tags, metadata, 
                       due_date, created_at, updated_at, completed_at, project, 
                       assignee, estimated_hours, actual_hours
                FROM todos 
                WHERE {where_clause}
                ORDER BY priority DESC, created_at DESC
            """
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            if rows:
                return rows
        except:
            pass
        
        # Strategy 2: Try word-by-word search
        try:
            # Split query into words and search for each
            words = [word.strip() for word in query.split() if len(word.strip()) > 2]
            if words:
                where_conditions = []
                params = []
                
                for word in words[:5]:  # Limit to first 5 words
                    where_conditions.append("(title LIKE ? OR description LIKE ?)")
                    word_pattern = f"%{word}%"
                    params.extend([word_pattern, word_pattern])
                
                if not include_completed:
                    where_conditions.append("state != ?")
                    params.append(self.COMPLETED)
                
                where_clause = " AND ".join(where_conditions)
                
                sql = f"""
                    SELECT id, title, description, state, priority, tags, metadata, 
                           due_date, created_at, updated_at, completed_at, project, 
                           assignee, estimated_hours, actual_hours
                    FROM todos 
                    WHERE {where_clause}
                    ORDER BY priority DESC, created_at DESC
                """
                
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                if rows:
                    return rows
        except:
            pass
        
        # Strategy 3: Return all recent todos as last resort
        try:
            where_conditions = []
            params = []
            
            if not include_completed:
                where_conditions.append("state != ?")
                params.append(self.COMPLETED)
            
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            
            sql = f"""
                SELECT id, title, description, state, priority, tags, metadata, 
                       due_date, created_at, updated_at, completed_at, project, 
                       assignee, estimated_hours, actual_hours
                FROM todos 
                WHERE {where_clause}
                ORDER BY priority DESC, created_at DESC
                LIMIT 20
            """
            
            cursor.execute(sql, params)
            return cursor.fetchall()
        except:
            return []
    
    def get_active_todos_summary(self) -> str:
        """Get a summary of active todos for context."""
        active_todos = self.list_todos(order_by="priority DESC, created_at", limit=10)
        active_todos = [t for t in active_todos if t['state'] != self.COMPLETED]
        
        if not active_todos:
            return "No active todos."
        
        summary_parts = ["=== ACTIVE TODOS ==="]
        
        # Group by state
        todo_items = [t for t in active_todos if t['state'] == self.TODO]
        in_progress_items = [t for t in active_todos if t['state'] == self.IN_PROGRESS]
        
        if in_progress_items:
            summary_parts.append("\n🔄 IN PROGRESS:")
            for todo in in_progress_items[:3]:  # Show top 3
                summary_parts.append(f"  • {todo['title']} [{todo['priority']}]")
        
        if todo_items:
            summary_parts.append("\n📋 TODO:")
            for todo in todo_items[:5]:  # Show top 5
                summary_parts.append(f"  • {todo['title']} [{todo['priority']}]")
        
        return "\n".join(summary_parts)
    
    def move_todo_to_state(self, todo_id: str, new_state: str) -> bool:
        """Move a todo to a different kanban state."""
        return self.update_todo(todo_id, state=new_state)
    
    def get_project_stats(self, project: str = None) -> Dict[str, Any]:
        """Get statistics for todos, optionally filtered by project."""
        where_clause = "WHERE project = ?" if project else "WHERE 1=1"
        params = [project] if project else []
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Count by state
            cursor.execute(f"""
                SELECT state, COUNT(*) as count 
                FROM todos {where_clause}
                GROUP BY state
            """, params)
            
            state_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Count by priority
            cursor.execute(f"""
                SELECT priority, COUNT(*) as count 
                FROM todos {where_clause} AND state != 'completed'
                GROUP BY priority
            """, params)
            
            priority_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Get overdue count (simplified - just check if due_date is past)
            cursor.execute(f"""
                SELECT COUNT(*) FROM todos 
                {where_clause} AND due_date < date('now') AND state != 'completed'
            """, params)
            
            overdue_count = cursor.fetchone()[0]
            
            return {
                'states': state_counts,
                'priorities': priority_counts,
                'overdue': overdue_count,
                'total': sum(state_counts.values())
            }
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert database row to dictionary."""
        return {
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'state': row[3],
            'priority': row[4],
            'tags': json.loads(row[5]) if row[5] else [],
            'metadata': json.loads(row[6]) if row[6] else {},
            'due_date': row[7],
            'created_at': row[8],
            'updated_at': row[9],
            'completed_at': row[10],
            'project': row[11],
            'assignee': row[12],
            'estimated_hours': row[13],
            'actual_hours': row[14]
        }