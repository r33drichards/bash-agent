# Bash Tools MCP Server

A Model Context Protocol (MCP) server that provides powerful development tools for bash command execution, SQLite database operations, and Python code execution via IPython.

## Features

This MCP server exposes three main tools:

### 1. Bash Tool
Execute shell commands with configurable timeouts and optional streaming output.

**Parameters:**
- `command` (required): The bash command to execute
- `timeout` (optional): Timeout in seconds (default: 30, max: 3600)
- `stream_output` (optional): Enable real-time output streaming (default: false)

**Example:**
```json
{
  "name": "bash",
  "arguments": {
    "command": "ls -la",
    "timeout": 10
  }
}
```

### 2. SQLite Tool
Execute SQL queries on SQLite databases with support for both read and write operations.

**Parameters:**
- `db_path` (required): Path to the SQLite database file
- `query` (required): SQL query to execute
- `output_json` (optional): Path to save SELECT results as JSON
- `print_result` (optional): Print results even when outputting to JSON (default: false)

**Example:**
```json
{
  "name": "sqlite",
  "arguments": {
    "db_path": "/path/to/database.db",
    "query": "SELECT * FROM users LIMIT 10"
  }
}
```

### 3. IPython Tool
Execute Python code in an IPython environment with support for rich output including matplotlib plots.

**Parameters:**
- `code` (required): Python code to execute
- `print_result` (optional): Print result in context window (default: false)

**Example:**
```json
{
  "name": "ipython",
  "arguments": {
    "code": "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.linspace(0, 10, 100)\nplt.plot(x, np.sin(x))\nplt.title('Sine Wave')\nplt.show()"
  }
}
```

The IPython tool automatically captures and returns matplotlib plots as base64-encoded PNG images.

## Installation

### Using Nix (Recommended)

If you have Nix with flakes enabled:

```bash
# Run directly
nix run github:r33drichards/bash-agent

# Or install to profile
nix profile install github:r33drichards/bash-agent
```

### Using pip

```bash
# Clone the repository
git clone https://github.com/r33drichards/bash-agent.git
cd bash-agent

# Install dependencies
pip install -r requirements.txt

# Run the server
python mcp_server.py
```

### Using Poetry/uv

```bash
# Clone the repository
git clone https://github.com/r33drichards/bash-agent.git
cd bash-agent

# Install with pip
pip install -e .

# Run the server
bash-tools-mcp-server
```

## Configuration

### Claude Desktop Integration

Add this to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "bash-tools": {
      "command": "bash-tools-mcp-server"
    }
  }
}
```

Or if using Nix:

```json
{
  "mcpServers": {
    "bash-tools": {
      "command": "nix",
      "args": ["run", "github:r33drichards/bash-agent"]
    }
  }
}
```

### Other MCP Clients

This server uses standard input/output (stdio) for communication, making it compatible with any MCP client that supports the stdio transport.

## Development

### Setting up development environment

```bash
# Using Nix
nix develop

# Or using pip
pip install -e ".[dev]"
```

### Running tests

```bash
pytest
```

### Code formatting

```bash
black .
```

## Security Considerations

⚠️ **Important Security Notes:**

- **Bash Tool**: Executes arbitrary shell commands with the same privileges as the server process. Use with caution and only in trusted environments.
- **SQLite Tool**: Can read and modify any SQLite database accessible to the server process.
- **IPython Tool**: Executes arbitrary Python code with full access to the Python environment and system resources.

**Recommendations:**
- Run the server with minimal necessary privileges
- Consider using containerization (Docker, Podman) to isolate the server
- Only connect to this server from trusted MCP clients
- Review and understand any commands/code before execution
- Use appropriate file system permissions to restrict database access

## Architecture

The server is built on:
- **MCP SDK**: Official Python SDK for Model Context Protocol
- **IPython**: Interactive Python shell for code execution
- **matplotlib**: For plot generation and visualization
- **sqlite3**: Python's built-in SQLite interface

The server implements the MCP protocol using stdio transport, making it lightweight and easy to integrate with any MCP-compatible client.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

## License

MIT

## Related Projects

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Claude Desktop](https://claude.ai/download)

## Changelog

### v0.1.0
- Initial release
- Support for bash command execution
- Support for SQLite database queries
- Support for IPython code execution with matplotlib plots
- Stdio transport for MCP communication
