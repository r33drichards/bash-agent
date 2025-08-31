# LLM Agent with Multiple Tools

**Warning!** This agent can execute bash commands, SQL queries, Python code, and modify files on your system. It is strongly recommended to run this inside a VM or Docker container to prevent accidental data loss.

## Quickstart

### Prerequisites

You need to have Nix installed to run the agent script:

```sh
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
```

### Running the Agent

Set your Anthropic API key and run the agent with Nix:

```sh
export ANTHROPIC_API_KEY=your-anthropic-key
nix run github:r33drichards/bash-agent#webagent -- --working-dir `pwd` --port 5556 --metadata-dir `pwd`/meta
```

running it locally 
```
nix run .#webagent -- --working-dir `pwd` --port 5556 --metadata-dir `pwd`/meta --mcp example-mcp-config.json
```

### What It Does

The agent launches an interactive loop where you can give it instructions. It has access to several tools:

1. **Bash Tool**: Execute shell commands
2. **SQLite Tool**: Query and modify SQLite databases
3. **IPython Tool**: Execute Python code with access to common libraries
4. **File Editing Tools**: 
   - Apply unified diffs to files
   - Overwrite files with new content

Before executing any tool, the agent will:
- Show you what it's about to do
- Ask for confirmation
- For file edits, show a preview of the changes


### Local Development

Clone the repository:

```sh
git clone git@github.com:r33drichards/bash-agent.git
cd bash-agent
```

Install dependencies (recommended: use Nix):

```sh
nix develop
```


Run the agent:

```sh
export ANTHROPIC_API_KEY=your-anthropic-key
python agent.py
```

### Security Warning

This agent can:
- Execute arbitrary bash commands
- Run SQL queries on any SQLite database
- Execute Python code
- Modify or overwrite any file on your system

**Use with caution and preferably in an isolated environment.**