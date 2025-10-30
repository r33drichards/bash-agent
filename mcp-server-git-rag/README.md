# MCP Server for Git Repository RAG

A Model Context Protocol (MCP) server that provides Retrieval Augmented Generation (RAG) capabilities for Git repositories. This server allows you to index Git repositories into a vector database and query them using natural language.

## Features

- **Index Git Repositories**: Clone and index any Git repository into a searchable vector database
- **Natural Language Queries**: Ask questions about codebases and get answers with citations
- **File Filtering**: Control which files to include by extension or directory
- **Citation Support**: Get specific file paths and code snippets with answers
- **Persistent Storage**: Indexed repositories are stored and can be queried repeatedly

## Installation

### Using pip

```bash
cd mcp-server-git-rag
pip install -e .
```

### Using Nix

The MCP server can be built and run using Nix (configuration in parent flake.nix).

## Configuration

### Environment Variables

- `OPENAI_API_KEY` (required): OpenAI API key for embeddings and LLM
- `GIT_RAG_PERSIST_DIR` (optional): Directory for vector database storage (default: `./git_rag_storage`)

### MCP Configuration

Add to your MCP settings file (e.g., `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "git-rag": {
      "command": "mcp-server-git-rag",
      "env": {
        "OPENAI_API_KEY": "your-openai-api-key",
        "GIT_RAG_PERSIST_DIR": "/path/to/storage"
      }
    }
  }
}
```

Or using uv:

```json
{
  "mcpServers": {
    "git-rag": {
      "command": "uvx",
      "args": ["mcp-server-git-rag"],
      "env": {
        "OPENAI_API_KEY": "your-openai-api-key"
      }
    }
  }
}
```

## Available Tools

### `index_repository`

Index a Git repository for RAG queries.

**Parameters:**
- `repo_url` (string, required): Git repository URL to clone and index
- `include_extensions` (array, optional): List of file extensions to include (e.g., `["py", "js", "md"]`)
- `ignore_dirs` (array, optional): List of directories to ignore (e.g., `["node_modules", "venv"]`)
- `force_reindex` (boolean, optional): Force re-indexing even if already indexed

**Example:**
```json
{
  "repo_url": "https://github.com/user/repo",
  "include_extensions": ["py", "md"],
  "ignore_dirs": ["tests", "docs"]
}
```

### `query_repository`

Query an indexed repository using natural language.

**Parameters:**
- `collection_name` (string, required): Collection name from indexed repository
- `question` (string, required): Question to ask about the codebase
- `max_results` (integer, optional): Maximum number of code snippets to retrieve (default: 5)

**Example:**
```json
{
  "collection_name": "repo_myproject",
  "question": "How does the authentication system work?",
  "max_results": 5
}
```

### `list_repositories`

List all indexed repositories and their collection names.

**Parameters:** None

## Usage Examples

### Indexing a Repository

```
Use index_repository tool:
- repo_url: https://github.com/anthropics/anthropic-sdk-python
- include_extensions: ["py", "md"]
```

### Querying a Repository

```
Use query_repository tool:
- collection_name: repo_anthropic_sdk_python
- question: How do I use streaming with the API?
```

### Listing Repositories

```
Use list_repositories tool
```

## How It Works

1. **Indexing**: The server clones the repository, extracts text from files, splits them into chunks, generates embeddings using OpenAI, and stores them in a Chroma vector database.

2. **Querying**: When you ask a question, the server:
   - Finds the most relevant code chunks using semantic search
   - Constructs a prompt with the code context
   - Uses an LLM to generate an answer with citations
   - Returns the answer along with source file references

## Technical Details

- **Embeddings**: OpenAI text-embedding-ada-002
- **Vector Store**: ChromaDB
- **LLM**: OpenAI GPT-3.5-turbo (configurable)
- **Framework**: LangChain for RAG pipeline
- **Protocol**: Model Context Protocol (MCP)

## Limitations

- Requires OpenAI API key and credits
- Large repositories may take time to index
- Binary files are automatically excluded
- Files larger than 100KB are skipped by default

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black src/
ruff check src/
```

## License

Same as parent project (bash-agent)

## Contributing

Contributions are welcome! Please see the parent project for guidelines.
