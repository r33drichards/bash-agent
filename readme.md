# Bash Agent

**Warning!** This agent executes bash commands on your local shell. It is recommended to run this inside a VM or Docker container to prevent accidental data loss.

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
nix run github:r33drichards/bash-agent -- --prompt-file myprompt.md
```

Or, if running directly with Python:

```sh
export ANTHROPIC_API_KEY=your-anthropic-key
python agent.py --prompt-file myprompt.md
```

### What It Does

- The agent launches an interactive loop where you can type instructions.
- When a bash command is to be executed, the agent will ask for confirmation before running it.
- All bash commands are executed in your local shell, and their output is shown in the conversation.

### Example Usage

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

Or, with pip (not recommended, but possible):

```sh
pip install anthropic tenacity
```

Run the agent:

```sh
export ANTHROPIC_API_KEY=your-anthropic-key
python agent.py
```

### Security Warning

This agent can execute arbitrary bash commands. Use with caution and preferably in an isolated environment.
