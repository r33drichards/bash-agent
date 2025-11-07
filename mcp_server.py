#!/usr/bin/env python3
"""
MCP Server for Bash, SQLite, and IPython tools
Exposes command execution, database queries, and Python code execution as MCP tools
"""

import asyncio
import logging
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Import tool implementations
from tools.bash_tool import execute_bash, bash_tool
from tools.sqlite_tool import execute_sqlite, sqlite_tool
from tools.ipython_tool import execute_ipython, ipython_tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create server instance
app = Server("bash-tools-mcp-server")


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools.
    Each tool defines its name, description, and input schema.
    """
    return [
        types.Tool(
            name=bash_tool["name"],
            description=bash_tool["description"],
            inputSchema=bash_tool["input_schema"],
        ),
        types.Tool(
            name=sqlite_tool["name"],
            description=sqlite_tool["description"],
            inputSchema=sqlite_tool["input_schema"],
        ),
        types.Tool(
            name=ipython_tool["name"],
            description=ipython_tool["description"],
            inputSchema=ipython_tool["input_schema"],
        ),
    ]


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """
    Handle tool execution requests.
    Executes the requested tool and returns the results.
    """
    if not arguments:
        arguments = {}

    logger.info(f"Executing tool: {name} with arguments: {arguments}")

    try:
        if name == "bash":
            command = arguments.get("command")
            if not command:
                raise ValueError("'command' parameter is required for bash tool")

            timeout = arguments.get("timeout", 30)
            stream_output = arguments.get("stream_output", False)

            result = execute_bash(command, timeout, stream_output)

            return [
                types.TextContent(
                    type="text",
                    text=result,
                )
            ]

        elif name == "sqlite":
            db_path = arguments.get("db_path")
            query = arguments.get("query")

            if not db_path:
                raise ValueError("'db_path' parameter is required for sqlite tool")
            if not query:
                raise ValueError("'query' parameter is required for sqlite tool")

            output_json = arguments.get("output_json")
            print_result = arguments.get("print_result", False)

            result = execute_sqlite(db_path, query, output_json, print_result)

            return [
                types.TextContent(
                    type="text",
                    text=result,
                )
            ]

        elif name == "ipython":
            code = arguments.get("code")
            if not code:
                raise ValueError("'code' parameter is required for ipython tool")

            print_result = arguments.get("print_result", False)

            output_text, plots = execute_ipython(code, print_result)

            results = [
                types.TextContent(
                    type="text",
                    text=output_text,
                )
            ]

            # Add plot images if any were generated
            if plots:
                for i, plot_data in enumerate(plots):
                    results.append(
                        types.ImageContent(
                            type="image",
                            data=plot_data,
                            mimeType="image/png",
                        )
                    )

            return results

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.error(f"Error executing tool {name}: {str(e)}")
        return [
            types.TextContent(
                type="text",
                text=f"Error executing {name}: {str(e)}",
            )
        ]


async def main():
    """Main entry point for the MCP server"""
    # Run the server using stdin/stdout streams
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="bash-tools-mcp-server",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
