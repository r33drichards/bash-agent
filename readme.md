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
nix run github:r33drichards/bash-agent
```

By default, the agent uses `prompt.md` as the system prompt. You can specify a custom prompt file with the `--prompt-file` flag:

```sh
nix run github:r33drichards/bash-agent -- --prompt-file prompt.md
```

You can also provide an initial user input to start the conversation:

```sh
nix run github:r33drichards/bash-agent -- --initial-user-input "List all Python files in the current directory"
```

Or, if running directly with Python:

```sh
export ANTHROPIC_API_KEY=your-anthropic-key
python agent.py --prompt-file myprompt.md
python agent.py --initial-user-input "Create a simple Python script"
```

#### Running With=== LLM Agent Loop with Claude and Bash Tool ===

Type 'exit' to end the conversation.



An error occurred: ANTHROPIC_API_KEY environment variable not found.
```sh
 docker run -it -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -v $(pwd):/app -w /app nixos/nix nix --extra-experimental-features 'nix-command flakes' run github:r33drichards/bash-agent -- --initial-user-input "what is the capital of france" --prompt-file prompt.md

 ```

### Command Line Arguments

- `--prompt-file`: Path to a custom prompt file (default: uses built-in prompt)
- `--initial-user-input`: Initial user input to start the conversation (default: None)

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

### Available Python Libraries

The IPython environment includes these pre-installed libraries:
- numpy
- matplotlib
- scikit-learn
- torch (PyTorch)
- pandas
- seaborn
- opencv-python
- gymnasium
- tensorboard
- And more...

### Example Usage

#### Basic Bash Command
```sh
$ nix run github:r33drichards/bash-agent
=== LLM Agent Loop with Claude and Bash Tool ===
Type 'exit' to end the conversation.

You: echo Hello World
Agent: About to execute bash command:

echo Hello World
Enter to confirm or x to cancel
Executing bash command: echo Hello World
Bash output:
STDOUT:
Hello World
STDERR:

EXIT CODE: 0
```

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