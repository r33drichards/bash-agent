import os
import json
from typing import Optional
from datetime import datetime
from flask import current_app
from flask_socketio import emit

from .session_manager import sessions


class MCPClient:
    """MCP Client for connecting to MCP servers and executing tools"""

    def __init__(self):
        try:
            from contextlib import AsyncExitStack
            from mcp import ClientSession
            self.session: Optional[ClientSession] = None
            self.exit_stack = AsyncExitStack()
        except ImportError:
            self.session = None
            self.exit_stack = None
        self.servers = {}
        self.available_tools = []
        self.is_initialized = False

    async def load_config_and_connect(self, config_path: str, working_dir: str = None):
        """Load MCP configuration and connect to servers"""
        try:
            from mcp import StdioServerParameters
        except ImportError:
            print("MCP not installed, skipping MCP client initialization")
            return
        
        try:
            print(f"DEBUG: MCPClient trying to open config file: {config_path}")
            print(f"DEBUG: MCPClient current working directory: {os.getcwd()}")

            # Use provided working_dir or fallback to current directory
            filesystem_dir = working_dir or os.getcwd()

            # Hard-coded default config to ensure filesystem server is always available
            example_config = {
                "mcpServers": {
                    "filesystem": {
                        "command": "mcp-server-filesystem",
                        "args": [filesystem_dir],
                    },
                    "playwright": {"command": "mcp-server-playwright"},
                    "sequentialthinking": {"command": "mcp-server-sequential-thinking"},
                    "memory": {"command": "mcp-server-memory"},
                }
            }
            print(
                f"DEBUG: Using hard-coded default config with {len(example_config.get('mcpServers', {}))} servers"
            )

            # Load user config
            user_config = {}
            if config_path and os.path.exists(config_path):
                with open(config_path, "r") as f:
                    user_config = json.load(f)
                print(
                    f"DEBUG: Loaded user config with {len(user_config.get('mcpServers', {}))} servers"
                )

            # Merge configs: example config first, then user config (user overrides example)
            merged_servers = {}
            merged_servers.update(example_config.get("mcpServers", {}))
            merged_servers.update(user_config.get("mcpServers", {}))

            config = {"mcpServers": merged_servers}

            if not merged_servers:
                print("Warning: No mcpServers found in merged MCP config")
                return

            print(
                f"DEBUG: Merged config has {len(merged_servers)} servers: {list(merged_servers.keys())}"
            )

            for server_name, server_config in config["mcpServers"].items():
                await self.connect_to_server(server_name, server_config)

            self.is_initialized = True
            print(f"MCP initialized with {len(self.servers)} servers")

        except Exception as e:
            print(f"Error loading MCP config: {e}")

    async def connect_to_server(self, server_name: str, server_config: dict):
        """Connect to a single MCP server"""
        try:
            from mcp import StdioServerParameters, ClientSession
            from mcp.client.stdio import stdio_client
        except ImportError:
            print(f"MCP not available, skipping server {server_name}")
            return
            
        try:
            command = server_config.get("command")
            args = server_config.get("args", [])
            env = server_config.get("env", {})

            if not command:
                print(f"Warning: No command specified for server {server_name}")
                return

            server_params = StdioServerParameters(command=command, args=args, env=env)

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write)
            )

            await session.initialize()

            # Get available tools
            response = await session.list_tools()
            tools = response.tools

            self.servers[server_name] = {
                "session": session,
                "tools": tools,
                "config": server_config,
            }

            # Add tools to available tools list with server prefix
            for tool in tools:
                tool_info = {
                    "name": f"{server_name}_{tool.name}",
                    "original_name": tool.name,
                    "server_name": server_name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                self.available_tools.append(tool_info)

            print(
                f"Connected to MCP server '{server_name}' with {len(tools)} tools: {[tool.name for tool in tools]}"
            )

        except Exception as e:
            print(f"Error connecting to MCP server '{server_name}': {e}")

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Call a tool on the appropriate MCP server"""
        try:
            # Find the tool and server
            tool_info = None
            for tool in self.available_tools:
                if tool["name"] == tool_name:
                    tool_info = tool
                    break

            if not tool_info:
                return {"error": f"Tool {tool_name} not found"}

            server_name = tool_info["server_name"]
            original_name = tool_info["original_name"]

            if server_name not in self.servers:
                return {"error": f"Server {server_name} not connected"}

            session = self.servers[server_name]["session"]
            result = await session.call_tool(original_name, args)

            return {
                "success": True,
                "content": result.content
                if hasattr(result, "content")
                else str(result),
            }

        except Exception as e:
            return {"error": f"Error calling tool {tool_name}: {str(e)}"}

    def get_tools_for_anthropic(self) -> list:
        """Get tools in the format expected by Anthropic API"""
        anthropic_tools = []
        for tool in self.available_tools:
            anthropic_tools.append(
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                }
            )
        return anthropic_tools

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def initialize_mcp_client(session_id, mcp_config_path=None, socketio=None, working_dir=None):
    """Initialize MCP client for the session"""
    try:
        if session_id not in sessions:
            return

        session_data = sessions[session_id]
        mcp_client = session_data.get("mcp_client")

        if not mcp_client:
            return

        config_path = mcp_config_path
        # Always try to load config - load_config_and_connect handles None gracefully
        # and will load the default config if no user config is provided

        if config_path:
            print(f"DEBUG: About to load MCP config from: {config_path}")
            print(f"DEBUG: Current working directory: {os.getcwd()}")
            print(f"DEBUG: Config file exists: {os.path.exists(config_path)}")
        else:
            print("DEBUG: No user MCP config provided, will load default config")

        await mcp_client.load_config_and_connect(config_path, working_dir)
        sessions[session_id]["mcp_initialized"] = True

        # Update the LLM with MCP tools
        llm = sessions[session_id]["llm"]
        if mcp_client.is_initialized:
            mcp_tools = mcp_client.get_tools_for_anthropic()
            llm.tools.extend(mcp_tools)

        # Debug output for MCP tools
        tool_list = [
            f"{tool['name']} ({tool['server_name']})"
            for tool in mcp_client.available_tools
        ]
        print(f"=== MCP INITIALIZATION DEBUG ===")
        print(f"Servers connected: {list(mcp_client.servers.keys())}")
        print(f"Available MCP tools: {tool_list}")
        print(f"================================")

        if socketio:
            socketio.emit(
                "message",
                {
                    "type": "system",
                    "content": f"MCP client initialized with {len(mcp_client.servers)} servers and {len(mcp_client.available_tools)} tools: {', '.join([tool['name'] for tool in mcp_client.available_tools])}",
                    "timestamp": datetime.now().isoformat(),
                },
                room=session_id,
            )

    except Exception as e:
        if socketio:
            socketio.emit(
                "message",
                {
                    "type": "error",
                    "content": f"Error initializing MCP client: {str(e)}",
                    "timestamp": datetime.now().isoformat(),
                },
                room=session_id,
            )


async def handle_mcp_tool_call(session_id, tool_call):
    """Handle MCP tool call asynchronously"""
    try:
        if session_id not in sessions:
            return

        session_data = sessions[session_id]
        mcp_client = session_data.get("mcp_client")

        if not mcp_client:
            return

        result = await mcp_client.call_tool(tool_call["name"], tool_call["input"])

        if result.get("error"):
            content = result["error"]
        else:
            content = result.get("content", "No result returned")

        from flask_socketio import SocketIO
        socketio = SocketIO()
        socketio.emit(
            "tool_result",
            {
                "tool_use_id": tool_call["id"],
                "result": content,
                "timestamp": datetime.now().isoformat(),
            },
            room=session_id,
        )

    except Exception as e:
        from flask_socketio import SocketIO
        socketio = SocketIO()
        socketio.emit(
            "tool_result",
            {
                "tool_use_id": tool_call["id"],
                "result": f"Error executing MCP tool: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            },
            room=session_id,
        )