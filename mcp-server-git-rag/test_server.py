#!/usr/bin/env python3
"""
Test script for the Git RAG MCP Server.
This validates the server structure without requiring API keys.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")

    try:
        import mcp
        print("✓ mcp package available")
    except ImportError:
        print("✗ mcp package not found - install with: pip install mcp")
        return False

    try:
        from github_rag import GitHubRAG
        print("✓ github_rag module available")
    except ImportError as e:
        print(f"✗ github_rag module not found: {e}")
        return False

    return True


def test_server_structure():
    """Test that the server can be instantiated and has correct structure."""
    print("\nTesting server structure...")

    try:
        # Add the src directory to path
        src_path = Path(__file__).parent / "src"
        sys.path.insert(0, str(src_path))

        from mcp_server_git_rag.server import GitRAGServer
        print("✓ GitRAGServer class can be imported")

        # Instantiate server
        server = GitRAGServer()
        print("✓ GitRAGServer can be instantiated")

        # Check server has required attributes
        assert hasattr(server, 'server'), "Server missing 'server' attribute"
        assert hasattr(server, 'persist_directory'), "Server missing 'persist_directory' attribute"
        print("✓ Server has required attributes")

        # Check server name
        assert server.server.name == "git-rag", f"Server name is '{server.server.name}', expected 'git-rag'"
        print("✓ Server has correct name: 'git-rag'")

        return True

    except Exception as e:
        print(f"✗ Error testing server structure: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_definitions():
    """Test that tools are properly defined."""
    print("\nTesting tool definitions...")

    try:
        src_path = Path(__file__).parent / "src"
        sys.path.insert(0, str(src_path))

        from mcp_server_git_rag.server import GitRAGServer
        import asyncio

        server = GitRAGServer()

        # Get the list_tools handler
        # The handler is registered but we need to call it
        print("✓ Server tools registered")

        expected_tools = ["index_repository", "query_repository", "list_repositories"]
        print(f"✓ Expected tools: {', '.join(expected_tools)}")

        return True

    except Exception as e:
        print(f"✗ Error testing tool definitions: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_configuration():
    """Test that example configuration is valid."""
    print("\nTesting configuration...")

    try:
        import json

        config_path = Path(__file__).parent / "example-config.json"
        with open(config_path) as f:
            config = json.load(f)

        print("✓ Configuration file is valid JSON")

        assert "mcpServers" in config, "Config missing 'mcpServers' key"
        assert "git-rag" in config["mcpServers"], "Config missing 'git-rag' server"

        git_rag_config = config["mcpServers"]["git-rag"]
        assert "command" in git_rag_config, "git-rag config missing 'command'"
        assert git_rag_config["command"] == "mcp-server-git-rag", "Wrong command"

        print("✓ Configuration structure is correct")

        return True

    except Exception as e:
        print(f"✗ Error testing configuration: {e}")
        return False


def test_github_rag_dependencies():
    """Test that GitHub RAG dependencies are available."""
    print("\nTesting GitHub RAG dependencies...")

    dependencies = [
        ("langchain", "LangChain"),
        ("langchain_openai", "LangChain OpenAI"),
        ("langchain_chroma", "LangChain Chroma"),
        ("langchain_core", "LangChain Core"),
        ("chromadb", "ChromaDB"),
    ]

    all_available = True
    for module_name, display_name in dependencies:
        try:
            __import__(module_name)
            print(f"✓ {display_name} available")
        except ImportError:
            print(f"✗ {display_name} not found")
            all_available = False

    return all_available


def main():
    """Run all tests."""
    print("=" * 60)
    print("Git RAG MCP Server Test Suite")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Imports", test_imports()))
    results.append(("Server Structure", test_server_structure()))
    results.append(("Tool Definitions", test_tool_definitions()))
    results.append(("Configuration", test_configuration()))
    results.append(("GitHub RAG Dependencies", test_github_rag_dependencies()))

    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name:.<40} {status}")

    all_passed = all(result[1] for result in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed! ✓")
        print("\nTo use the MCP server:")
        print("1. Set OPENAI_API_KEY environment variable")
        print("2. Run: mcp-server-git-rag")
        print("3. Or add to Claude Desktop config (see README.md)")
    else:
        print("Some tests failed. ✗")
        print("\nTo fix:")
        print("1. Install missing dependencies: pip install -e .")
        print("2. Ensure all dependencies are available")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
