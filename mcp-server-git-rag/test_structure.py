#!/usr/bin/env python3
"""
Structure validation test for Git RAG MCP Server.
Tests code structure without requiring dependencies.
"""

import ast
import json
import sys
from pathlib import Path


def test_python_syntax():
    """Test that all Python files have valid syntax."""
    print("Testing Python syntax...")

    python_files = [
        "src/mcp_server_git_rag/__init__.py",
        "src/mcp_server_git_rag/server.py",
    ]

    all_valid = True
    for file_path in python_files:
        full_path = Path(__file__).parent / file_path
        try:
            with open(full_path) as f:
                code = f.read()
            ast.parse(code)
            print(f"✓ {file_path} - valid syntax")
        except SyntaxError as e:
            print(f"✗ {file_path} - syntax error: {e}")
            all_valid = False
        except FileNotFoundError:
            print(f"✗ {file_path} - file not found")
            all_valid = False

    return all_valid


def test_server_code_structure():
    """Test that server code has expected structure."""
    print("\nTesting server code structure...")

    server_path = Path(__file__).parent / "src/mcp_server_git_rag/server.py"

    try:
        with open(server_path) as f:
            code = f.read()

        tree = ast.parse(code)

        # Check for GitRAGServer class
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        if "GitRAGServer" not in classes:
            print("✗ GitRAGServer class not found")
            return False
        print("✓ GitRAGServer class found")

        # Check for main function
        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        if "main" not in functions:
            print("✗ main function not found")
            return False
        print("✓ main function found")

        # Check for expected methods
        expected_methods = ["_initialize_rag", "_register_handlers", "_index_repository", "_query_repository", "_list_repositories", "run"]

        for method in expected_methods:
            if method in functions:
                print(f"✓ {method} method found")
            else:
                print(f"✗ {method} method not found")
                return False

        # Check for required imports
        required_imports = ["mcp", "github_rag", "asyncio"]
        import_names = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_names.extend([alias.name for alias in node.names])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_names.append(node.module.split('.')[0])

        for imp in required_imports:
            if imp in import_names:
                print(f"✓ imports {imp}")
            else:
                print(f"✗ missing import: {imp}")
                return False

        return True

    except Exception as e:
        print(f"✗ Error analyzing server code: {e}")
        return False


def test_configuration_files():
    """Test configuration files."""
    print("\nTesting configuration files...")

    # Test pyproject.toml
    pyproject_path = Path(__file__).parent / "pyproject.toml"
    try:
        with open(pyproject_path) as f:
            content = f.read()

        required_sections = ["[build-system]", "[project]", "[project.scripts]"]
        for section in required_sections:
            if section in content:
                print(f"✓ pyproject.toml has {section}")
            else:
                print(f"✗ pyproject.toml missing {section}")
                return False

        # Check entry point
        if "mcp-server-git-rag = \"mcp_server_git_rag.server:main\"" in content:
            print("✓ Entry point configured correctly")
        else:
            print("✗ Entry point not configured correctly")
            return False

    except FileNotFoundError:
        print("✗ pyproject.toml not found")
        return False

    # Test example config
    config_path = Path(__file__).parent / "example-config.json"
    try:
        with open(config_path) as f:
            config = json.load(f)

        if "mcpServers" in config and "git-rag" in config["mcpServers"]:
            print("✓ example-config.json structure correct")
        else:
            print("✗ example-config.json structure incorrect")
            return False

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"✗ example-config.json error: {e}")
        return False

    return True


def test_documentation():
    """Test that documentation exists."""
    print("\nTesting documentation...")

    readme_path = Path(__file__).parent / "README.md"

    try:
        with open(readme_path) as f:
            content = f.read()

        required_sections = [
            "# MCP Server for Git Repository RAG",
            "## Features",
            "## Installation",
            "## Configuration",
            "## Available Tools",
            "## Usage Examples"
        ]

        for section in required_sections:
            if section in content:
                print(f"✓ README has '{section}'")
            else:
                print(f"✗ README missing '{section}'")
                return False

        return True

    except FileNotFoundError:
        print("✗ README.md not found")
        return False


def main():
    """Run all structure tests."""
    print("=" * 60)
    print("Git RAG MCP Server Structure Validation")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Python Syntax", test_python_syntax()))
    results.append(("Server Code Structure", test_server_code_structure()))
    results.append(("Configuration Files", test_configuration_files()))
    results.append(("Documentation", test_documentation()))

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
        print("Structure validation passed! ✓")
        print("\nNext steps:")
        print("1. Install dependencies with Nix: nix develop")
        print("2. Or install with pip: pip install -e .")
        print("3. Set OPENAI_API_KEY environment variable")
        print("4. Run: mcp-server-git-rag")
        print("5. Or use with bash-agent: see test-mcp-integration.sh")
    else:
        print("Structure validation failed. ✗")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
