import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
import os

class MemoryManager:
    """Manages persistent memory storage for the agent using SQLite."""
    
    def __init__(self, db_path: str = "meta/memory.db"):
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
    
    def _init_database(self):
        """Initialize the memory database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create memories table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for faster searches
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_title ON memories(title)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)
            """)
            
            conn.commit()
    
    def save_memory(self, title: str, content: str, tags: List[str] = None, metadata: Dict[str, Any] = None) -> str:
        """Save a new memory and return its ID."""
        memory_id = str(uuid.uuid4())
        tags_str = json.dumps(tags) if tags else "[]"
        metadata_str = json.dumps(metadata) if metadata else "{}"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO memories (id, title, content, tags, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (memory_id, title, content, tags_str, metadata_str))
            conn.commit()
        
        return memory_id
    
    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific memory by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE memories SET accessed_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (memory_id,))
            
            cursor.execute("""
                SELECT id, title, content, tags, metadata, created_at, updated_at, accessed_at
                FROM memories WHERE id = ?
            """, (memory_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'tags': json.loads(row[3]),
                    'metadata': json.loads(row[4]),
                    'created_at': row[5],
                    'updated_at': row[6],
                    'accessed_at': row[7]
                }
            conn.commit()
        
        return None
    
    def search_memories(self, query: str = None, tags: List[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Search memories by content, title, or tags."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            where_conditions = []
            params = []
            
            if query:
                # Validate query length and complexity
                MAX_QUERY_LENGTH = 10000
                if len(query) > MAX_QUERY_LENGTH:
                    # Truncate the query and warn the user
                    query = query[:MAX_QUERY_LENGTH]
                    import warnings
                    warnings.warn(f"Search query truncated from original length to {MAX_QUERY_LENGTH} characters")
                
                where_conditions.append("(title LIKE ? OR content LIKE ?)")
                query_pattern = f"%{query}%"
                params.extend([query_pattern, query_pattern])
            
            if tags:
                for tag in tags:
                    if len(tag) > 500:
                        raise ValueError(f"Tag search too long ({len(tag)} characters). Maximum allowed: 500 characters.")
                    where_conditions.append("tags LIKE ?")
                    params.append(f"%{tag}%")
            
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            
            sql = f"""
                SELECT id, title, content, tags, metadata, created_at, updated_at, accessed_at
                FROM memories 
                WHERE {where_clause}
                ORDER BY accessed_at DESC, created_at DESC
                LIMIT ?
            """
            params.append(limit)
            
            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError as e:
                if "LIKE or GLOB pattern too complex" in str(e):
                    # Fallback: try simplified search strategies
                    rows = self._fallback_search(cursor, query, tags, limit)
                else:
                    raise ValueError(f"Database search error: {str(e)}. Query: '{query}'")
            
            results = []
            for row in rows:
                results.append({
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'tags': json.loads(row[3]),
                    'metadata': json.loads(row[4]),
                    'created_at': row[5],
                    'updated_at': row[6],
                    'accessed_at': row[7]
                })
            
            return results
    
    def _fallback_search(self, cursor, query: str, tags: List[str] = None, limit: int = 20):
        """Fallback search when LIKE pattern is too complex."""
        # Strategy 1: Try exact match first
        try:
            where_conditions = []
            params = []
            
            if query:
                where_conditions.append("(title = ? OR content = ?)")
                params.extend([query, query])
            
            if tags:
                for tag in tags:
                    where_conditions.append("tags = ?")
                    params.append(tag)
            
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            
            sql = f"""
                SELECT id, title, content, tags, metadata, created_at, updated_at, accessed_at
                FROM memories 
                WHERE {where_clause}
                ORDER BY accessed_at DESC, created_at DESC
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            if rows:
                return rows
        except:
            pass
        
        # Strategy 2: Try word-by-word search
        try:
            if query:
                # Split query into words and search for each
                words = [word.strip() for word in query.split() if len(word.strip()) > 2]
                if words:
                    where_conditions = []
                    params = []
                    
                    for word in words[:5]:  # Limit to first 5 words
                        where_conditions.append("(title LIKE ? OR content LIKE ?)")
                        word_pattern = f"%{word}%"
                        params.extend([word_pattern, word_pattern])
                    
                    where_clause = " OR ".join(where_conditions)
                    
                    sql = f"""
                        SELECT id, title, content, tags, metadata, created_at, updated_at, accessed_at
                        FROM memories 
                        WHERE {where_clause}
                        ORDER BY accessed_at DESC, created_at DESC
                        LIMIT ?
                    """
                    params.append(limit)
                    
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    if rows:
                        return rows
        except:
            pass
        
        # Strategy 3: Return all recent memories as last resort
        try:
            sql = """
                SELECT id, title, content, tags, metadata, created_at, updated_at, accessed_at
                FROM memories 
                ORDER BY accessed_at DESC, created_at DESC
                LIMIT ?
            """
            cursor.execute(sql, [limit])
            return cursor.fetchall()
        except:
            return []
    
    def update_memory(self, memory_id: str, title: str = None, content: str = None, 
                     tags: List[str] = None, metadata: Dict[str, Any] = None) -> bool:
        """Update an existing memory."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if title is not None:
                updates.append("title = ?")
                params.append(title)
            
            if content is not None:
                updates.append("content = ?")
                params.append(content)
            
            if tags is not None:
                updates.append("tags = ?")
                params.append(json.dumps(tags))
            
            if metadata is not None:
                updates.append("metadata = ?")
                params.append(json.dumps(metadata))
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(memory_id)
            
            sql = f"UPDATE memories SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(sql, params)
            
            success = cursor.rowcount > 0
            conn.commit()
            return success
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            success = cursor.rowcount > 0
            conn.commit()
            return success
    
    def list_memories(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List all memories with pagination."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, content, tags, metadata, created_at, updated_at, accessed_at
                FROM memories 
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'tags': json.loads(row[3]),
                    'metadata': json.loads(row[4]),
                    'created_at': row[5],
                    'updated_at': row[6],
                    'accessed_at': row[7]
                })
            
            return results
    
    def get_memory_context(self, query: str = None, max_memories: int = 5) -> str:
        """Get relevant memories as context string for the agent."""
        memories = self.search_memories(query=query, limit=max_memories)
        
        if not memories:
            return "No relevant memories found."
        
        context_parts = ["=== RELEVANT MEMORIES ==="]
        for memory in memories:
            context_parts.append(f"\nTitle: {memory['title']}")
            if memory['tags']:
                context_parts.append(f"Tags: {', '.join(memory['tags'])}")
            context_parts.append(f"Content: {memory['content']}")
            context_parts.append("---")
        
        return "\n".join(context_parts)