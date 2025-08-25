# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a multi-tool LLM agent that can execute bash commands, SQL queries, Python code, and modify files. The agent provides both a web interface and CLI interface for interacting with Claude.

### Core Architecture

- **Web Mode**: Flask application with SocketIO for real-time communication
- **CLI Mode**: Direct command-line interaction through `bash-agent.py`
- **Agent System**: Modular architecture with separate tools for different functionalities
- **Session Management**: Persistent conversations with memory and todo tracking
- **MCP Integration**: Support for Model Context Protocol servers

### Key Components

- `main.py` - Web server entry point with argument parsing and configuration
- `bash-agent.py` - CLI entry point for direct command-line usage
- `app_factory.py` - Flask application factory with route registration
- `agent/` - Core agent logic including LLM client, session management, and tools
- `routes/` - Web API and UI routes
- `tools/` - Individual tool implementations (bash, sqlite, ipython, etc.)
- `templates/` - HTML templates for the web interface

## Common Development Commands

### Running the Application


**With Nix (if available):**
```bash
export ANTHROPIC_API_KEY=your-anthropic-key
nix run .#webAgent -- --working-dir $(pwd) --port 5556 --metadata-dir $(pwd)/meta
```

### Development Environment


### Testing

Run tests with:
```bash
nix build .#webAgent
```
this uses nix to build the app and also runs pytest

## Configuration Options

### Command Line Arguments

- `--port` - Web server port (default: 5000)
- `--host` - Server host (default: 0.0.0.0)
- `--working-dir` - Working directory for tool execution
- `--metadata-dir` - Directory for conversation history and metadata
- `--auto-confirm` - Skip confirmation prompts for tool execution
- `--system-prompt` - Custom system prompt file
- `--mcp` - Path to MCP configuration JSON file

### MCP Configuration

The system supports MCP (Model Context Protocol) servers. Example configuration in `example-mcp-config.json`:
```json
{
  "mcpServers": {
    "playwright": {"command": "mcp-server-playwright"},
    "sequentialthinking": {"command": "mcp-server-sequential-thinking"},
    "memory": {"command": "mcp-server-memory"}
  }
}
```

### Environment Variables

- `ANTHROPIC_API_KEY` - Required for Claude API access
- `OPENAI_API_KEY` - Optional, for GitHub RAG functionality

## Available Tools

### Built-in Tools

1. **Bash Tool** - Execute shell commands with confirmation prompts
2. **SQLite Tool** - Query and modify SQLite databases
3. **IPython Tool** - Execute Python code with rich output support
4. **File Editing Tools** - Apply diffs or overwrite files
5. **Todo Tools** - Create and manage task lists
6. **GitHub RAG Tools** - Index and query GitHub repositories
7. **Memory Tools** - Store and retrieve conversation memory (legacy)

### Security Considerations

- All tool executions require user confirmation by default (unless `--auto-confirm` is used)
- File operations show previews before execution
- File browser restricts access to specified working directory
- Path traversal attacks are prevented by `is_safe_path()` checks

## Database Storage

The application uses SQLite databases stored in the metadata directory:
- `memory.db` - Legacy memory storage
- `sessions.db` - Session management
- `todos.db` - Todo list storage

## Web Interface Features

- Real-time streaming responses via WebSocket
- File browser with upload/download capabilities
- Token usage tracking and display
- Session persistence and conversation history
- Thinking mode support with collapsible blocks

## Development Notes

- Uses Flask-SocketIO for real-time communication
- Implements message validation to prevent orphaned tool results
- Supports both streaming and non-streaming API responses
- Handles Claude's thinking mode requirements for conversation history
- Includes comprehensive error handling and retry logic with exponential backoff