#!/bin/bash
# Integration test for Git RAG functionality
# Tests the GitHub RAG module that powers the MCP server

set -e

echo "=========================================="
echo "Git RAG Integration Test"
echo "=========================================="

# Check for API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY environment variable not set"
    exit 1
fi

echo "✓ OPENAI_API_KEY is set"

# Create test directory
TEST_DIR=$(mktemp -d)
echo "✓ Created test directory: $TEST_DIR"

# Export test directory for cleanup
trap "rm -rf $TEST_DIR" EXIT

# Create test Python script
cat > "$TEST_DIR/test_rag.py" << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""Test GitHub RAG functionality."""

import os
import sys
import tempfile
from pathlib import Path

# Add bash-agent directory to path
bash_agent_dir = Path("/home/user/bash-agent")
sys.path.insert(0, str(bash_agent_dir))

from github_rag import GitHubRAG

def test_initialization():
    """Test that GitHubRAG can be initialized."""
    print("\n1. Testing GitHubRAG initialization...")

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        print("✗ OPENAI_API_KEY not set")
        return False

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rag = GitHubRAG(
                openai_api_key=openai_api_key,
                persist_directory=temp_dir
            )
            print("✓ GitHubRAG initialized successfully")
            print(f"✓ Persist directory: {rag.persist_directory}")
            return True
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_repository_functions():
    """Test repository helper functions."""
    print("\n2. Testing repository helper functions...")

    openai_api_key = os.environ.get("OPENAI_API_KEY")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rag = GitHubRAG(
                openai_api_key=openai_api_key,
                persist_directory=temp_dir
            )

            # Test should_process_file
            test_cases = [
                ("/path/to/file.py", [".git"], None, True),
                ("/path/.git/config", [".git"], None, False),
                ("/path/to/file.py", [], ["py"], True),
                ("/path/to/file.js", [], ["py"], False),
            ]

            for file_path, ignore_dirs, include_exts, expected in test_cases:
                result = rag.should_process_file(file_path, ignore_dirs, include_exts)
                if result == expected:
                    print(f"✓ should_process_file({file_path}) = {result}")
                else:
                    print(f"✗ should_process_file({file_path}) expected {expected}, got {result}")
                    return False

            # Test list_repositories (should be empty)
            repos = rag.list_repositories()
            if repos == []:
                print("✓ list_repositories returns empty list initially")
            else:
                print(f"✗ Expected empty list, got {repos}")
                return False

            return True

    except Exception as e:
        print(f"✗ Error testing repository functions: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_indexing_local_repo():
    """Test indexing the bash-agent repository itself."""
    print("\n3. Testing indexing of bash-agent repository...")

    openai_api_key = os.environ.get("OPENAI_API_KEY")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rag = GitHubRAG(
                openai_api_key=openai_api_key,
                persist_directory=temp_dir
            )

            # Use a small subset by filtering to just Python and Markdown files
            repo_url = "https://github.com/r33drichards/bash-agent"

            print(f"   Indexing repository: {repo_url}")
            print("   (This will take a moment...)")

            result = rag.index_repository(
                repo_url=repo_url,
                include_extensions=["py", "md"],
                ignore_dirs=[".git", "node_modules", "__pycache__", ".github"],
                max_chunk_count=100  # Limit to 100 chunks for faster testing
            )

            if result.get("success"):
                print(f"✓ Repository indexed successfully")
                print(f"  Collection: {result['collection_name']}")
                print(f"  Documents: {result.get('document_count', 0)}")
                print(f"  Chunks: {result.get('chunk_count', 0)}")

                # Test querying
                print("\n4. Testing query on indexed repository...")

                query_result = rag.query_repository(
                    collection_name=result['collection_name'],
                    question="What tools does the bash agent have?",
                    max_results=3
                )

                if query_result.get("success"):
                    print("✓ Query executed successfully")
                    print(f"  Question: {query_result['question']}")
                    print(f"  Sources found: {query_result['total_sources']}")
                    print(f"\n  Answer snippet:")
                    answer = query_result['answer']
                    # Print first 200 chars of answer
                    print(f"  {answer[:200]}...")
                    return True
                else:
                    print(f"✗ Query failed: {query_result.get('error')}")
                    return False
            else:
                print(f"✗ Indexing failed: {result.get('error')}")
                return False

    except Exception as e:
        print(f"✗ Error testing indexing: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("GitHub RAG Functionality Tests")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Initialization", test_initialization()))
    results.append(("Repository Functions", test_repository_functions()))
    results.append(("Indexing & Querying", test_indexing_local_repo()))

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
        print("\nThe Git RAG functionality is working correctly.")
        print("The MCP server uses this same functionality.")
    else:
        print("Some tests failed. ✗")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

PYTHON_SCRIPT

# Run the test
echo ""
echo "Running integration test..."
echo ""

cd /home/user/bash-agent
python3 "$TEST_DIR/test_rag.py"

TEST_RESULT=$?

if [ $TEST_RESULT -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "Integration test PASSED ✓"
    echo "=========================================="
    echo ""
    echo "The Git RAG MCP server is ready to use!"
    echo ""
    echo "To use it:"
    echo "1. Add to your MCP configuration (see example-mcp-config.json)"
    echo "2. Set OPENAI_API_KEY in the environment"
    echo "3. Run: mcp-server-git-rag"
    echo ""
else
    echo ""
    echo "=========================================="
    echo "Integration test FAILED ✗"
    echo "=========================================="
fi

exit $TEST_RESULT
