# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is an MCP (Model Context Protocol) server that exposes bash command execution, SQLite database operations, and IPython code execution as tools that can be used by MCP clients like Claude Desktop.

### Core Architecture

- **MCP Server**: Python-based server implementing the Model Context Protocol
- **Tool Implementations**: Modular tool implementations for bash, SQLite, and IPython
- **Stdio Transport**: Communication via standard input/output for easy integration

### Key Components

- `mcp_server.py` - Main MCP server implementation with tool registration and handling
- `tools/` - Tool implementations for bash, SQLite, and IPython execution
  - `bash_tool.py` - Execute shell commands with timeout and streaming support
  - `sqlite_tool.py` - Execute SQL queries on SQLite databases
  - `ipython_tool.py` - Execute Python code with matplotlib plot support
- `pyproject.toml` - Python package configuration
- `flake.nix` - Nix package definition for reproducible builds

## Common Development Commands

### Running the Server

**With Nix:**
```bash
nix run .
```

**With Python:**
```bash
python mcp_server.py
```

### Development Environment

**With Nix:**
```bash
nix develop
```

**With pip:**
```bash
pip install -e ".[dev]"
```

### Testing

```bash
pytest
```

### Building

```bash
nix build
```

## Tool Implementations

### Bash Tool
- Executes shell commands with configurable timeout
- Supports streaming output for long-running commands
- Returns stdout, stderr, and exit code

### SQLite Tool
- Executes SQL queries on SQLite databases
- Supports both read and write operations
- Can export SELECT results to JSON files

### IPython Tool
- Executes Python code in IPython environment
- Automatically captures matplotlib plots as base64 PNG
- Returns stdout, stderr, rich output, and generated plots

## Security Considerations

All tools execute with the privileges of the server process:
- Bash tool can execute arbitrary shell commands
- SQLite tool can access any database the process can read
- IPython tool can execute arbitrary Python code

Use appropriate sandboxing and access controls in production.

## Configuration

The server uses stdio transport and is designed to be configured in MCP client config files:

```json
{
  "mcpServers": {
    "bash-tools": {
      "command": "bash-tools-mcp-server"
    }
  }
}
```

## Development Notes

- Uses the official MCP Python SDK
- Implements async/await pattern for tool execution
- Each tool returns a list of MCP content types (TextContent, ImageContent)
- Error handling returns error messages as TextContent
