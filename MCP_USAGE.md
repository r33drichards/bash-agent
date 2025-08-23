# MCP (Model Context Protocol) Integration

This agent now supports MCP servers, allowing you to extend its capabilities with external tools and services.

## Usage

Run the agent with MCP configuration:

```bash
python agent.py --mcp /path/to/your/mcp-config.json
```

## MCP Configuration File

Create a JSON configuration file that defines your MCP servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/directory"],
      "env": {}
    },
    "sqlite": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sqlite", "/path/to/database.db"],
      "env": {}
    },
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Available MCP Servers

Popular MCP servers you can use:

1. **@modelcontextprotocol/server-filesystem** - File system operations
2. **@modelcontextprotocol/server-sqlite** - SQLite database operations  
3. **@modelcontextprotocol/server-brave-search** - Web search via Brave API
4. **@modelcontextprotocol/server-github** - GitHub repository operations
5. **@modelcontextprotocol/server-postgres** - PostgreSQL database operations
6. **@modelcontextprotocol/server-fetch** - HTTP requests and web scraping

## How It Works

1. When you start the agent with `--mcp`, it creates an MCP client
2. On first connection to the web interface, it initializes MCP servers asynchronously
3. MCP tools are added to the available tools with server name prefixes (e.g., `filesystem_read_file`)
4. The agent can now use these external tools in addition to built-in tools
5. MCP tools are listed in the system prompt for the LLM to understand

## Tool Naming Convention

MCP tools are prefixed with the server name:
- `filesystem_read_file` (from filesystem server)
- `brave-search_search` (from brave-search server)
- `github_create_repository` (from github server)

## Requirements

- Node.js and npm installed (for npx-based MCP servers)
- Appropriate API keys for services (Brave, GitHub, etc.)
- MCP server packages installed globally or available via npx

## Troubleshooting

- Check that your MCP configuration JSON is valid
- Ensure required API keys are set in environment variables
- Verify MCP server packages are accessible via npx
- Check the console output for MCP initialization messages