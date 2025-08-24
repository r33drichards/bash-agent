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

github_rag_list_tool = {
    "name": "github_rag_list",
    "description": "List all indexed GitHub repositories and their collection names for querying.",
    "input_schema": {
        "type": "object",
        "properties": {}
    }
}