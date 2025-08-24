import os
import argparse
from app_factory import create_app


def main():
    parser = argparse.ArgumentParser(description="LLM Agent Web Server")

    parser.add_argument(
        "--port", type=int, default=5000, help="Port to run the server on"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host to run the server on"
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Automatically confirm all actions without prompting",
    )
    parser.add_argument(
        "--working-dir",
        type=str,
        default=None,
        help="Set the working directory for tool execution",
    )
    parser.add_argument(
        "--metadata-dir",
        type=str,
        default=None,
        help="Directory to store conversation history and metadata",
    )
    # system prompt
    parser.add_argument(
        "--system-prompt",
        type=str,
        default=None,
        help="System prompt to use for the agent",
    )
    parser.add_argument(
        "--mcp", type=str, default=None, help="Path to MCP configuration JSON file"
    )
    args = parser.parse_args()

    # Store the original working directory BEFORE any changes
    original_cwd = os.getcwd()

    # Convert MCP config to absolute path using original working directory
    mcp_config_path = None
    if args.mcp:
        if os.path.isabs(args.mcp):
            mcp_config_path = args.mcp
        else:
            # Use original working directory for relative path resolution
            mcp_config_path = os.path.join(original_cwd, args.mcp)
        print(f"MCP config converted to absolute path: {mcp_config_path}")

    # Prepare configuration
    config = {
        "AUTO_CONFIRM": args.auto_confirm,
        "WORKING_DIR": args.working_dir,
        "METADATA_DIR": args.metadata_dir,
        "SYSTEM_PROMPT": args.system_prompt,
        "MCP_CONFIG": mcp_config_path,
    }

    # Change working directory if specified
    if args.working_dir:
        if os.path.exists(args.working_dir):
            os.chdir(args.working_dir)
            print(f"Working directory changed to: {args.working_dir}")
        else:
            print(f"Warning: Working directory {args.working_dir} does not exist")
            return

    # Set file browser root path after working directory is established
    config["FILE_BROWSER_ROOT"] = config["WORKING_DIR"]
    print(f"File browser root path: {config['FILE_BROWSER_ROOT']}")
    print(
        f"File browser access is restricted to: {config['FILE_BROWSER_ROOT']} and subdirectories only"
    )
    print(f"Security: Path traversal attacks are blocked by is_safe_path() checks")

    # Create metadata directory if specified
    if args.metadata_dir:
        if not os.path.exists(args.metadata_dir):
            os.makedirs(args.metadata_dir)
            print(f"Created metadata directory: {args.metadata_dir}")
        else:
            print(f"Using existing metadata directory: {args.metadata_dir}")

    print(f"\n=== LLM Agent Web Server ===")
    print(f"Starting server on http://{args.host}:{args.port}")
    print(f"Working directory: {os.getcwd()}")
    if args.mcp:
        print(f"MCP configuration: {args.mcp}")
        if os.path.exists(args.mcp):
            print(f"MCP config file exists: ✓")
        else:
            print(f"MCP config file NOT found: ✗")
    else:
        print("No MCP configuration specified")
    print("Claude Code-like interface available in your browser")

    # Create app and socketio
    app, socketio = create_app(config)

    socketio.run(
        app, host=args.host, port=args.port, debug=True, allow_unsafe_werkzeug=True
    )


if __name__ == "__main__":
    main()