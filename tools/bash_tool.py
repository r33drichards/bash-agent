bash_tool = {
    "name": "bash",
    "description": "Execute bash commands and return the output. Supports custom timeouts and real-time streaming for long-running commands.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30, max: 3600 for 1 hour)"
            },
            "stream_output": {
                "type": "boolean",
                "description": "Stream output in real-time for long-running commands (default: false)"
            }
        },
        "required": ["command"]
    }
}