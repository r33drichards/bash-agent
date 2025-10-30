#!/usr/bin/env python3
"""
Git Repository RAG MCP Server

This MCP server provides tools for indexing and querying Git repositories
using Retrieval Augmented Generation (RAG). It allows you to:
- Index GitHub/Git repositories into a vector database
- Query indexed repositories with natural language
- List all indexed repositories
"""

import os
import sys
import logging
import asyncio
from typing import Any, Optional
from pathlib import Path

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.server.stdio

# Add parent directory to path to import github_rag module
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from github_rag import GitHubRAG

logger = logging.getLogger(__name__)

class GitRAGServer:
    """MCP Server for Git Repository RAG."""

    def __init__(self):
        self.server = Server("git-rag")
        self.github_rag: Optional[GitHubRAG] = None
        self.persist_directory = os.environ.get("GIT_RAG_PERSIST_DIR", "./git_rag_storage")

        # Register handlers
        self._register_handlers()

    def _initialize_rag(self) -> GitHubRAG:
        """Initialize the GitHub RAG instance if not already initialized."""
        if self.github_rag is None:
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            if not openai_api_key:
                raise ValueError("OPENAI_API_KEY environment variable is required")

            self.github_rag = GitHubRAG(
                openai_api_key=openai_api_key,
                persist_directory=self.persist_directory
            )

        return self.github_rag

    def _register_handlers(self):
        """Register MCP handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools."""
            return [
                Tool(
                    name="index_repository",
                    description=(
                        "Index a Git repository for RAG queries. Clones the repository, "
                        "processes its files, and creates a searchable vector database. "
                        "Supports filtering by file extensions and ignoring specific directories."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_url": {
                                "type": "string",
                                "description": "Git repository URL to clone and index (e.g., https://github.com/user/repo)"
                            },
                            "include_extensions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of file extensions to include (e.g., ['py', 'js', 'md']). If not specified, all text files are included."
                            },
                            "ignore_dirs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of directories to ignore (e.g., ['node_modules', 'venv']). Default includes common ignore patterns."
                            },
                            "force_reindex": {
                                "type": "boolean",
                                "description": "Force re-indexing even if repository is already indexed",
                                "default": False
                            }
                        },
                        "required": ["repo_url"]
                    }
                ),
                Tool(
                    name="query_repository",
                    description=(
                        "Query an indexed Git repository using natural language. "
                        "Returns answers with citations to specific files and code snippets."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "collection_name": {
                                "type": "string",
                                "description": "The collection name of the indexed repository (use list_repositories to see available collections)"
                            },
                            "question": {
                                "type": "string",
                                "description": "The question to ask about the codebase"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of relevant code snippets to retrieve (default: 5)",
                                "default": 5
                            }
                        },
                        "required": ["collection_name", "question"]
                    }
                ),
                Tool(
                    name="list_repositories",
                    description="List all indexed Git repositories and their collection names.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            try:
                if name == "index_repository":
                    return await self._index_repository(arguments)
                elif name == "query_repository":
                    return await self._query_repository(arguments)
                elif name == "list_repositories":
                    return await self._list_repositories(arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
            except Exception as e:
                logger.error(f"Error executing tool {name}: {e}", exc_info=True)
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

    async def _index_repository(self, arguments: dict) -> list[TextContent]:
        """Index a Git repository."""
        repo_url = arguments.get("repo_url")
        include_extensions = arguments.get("include_extensions")
        ignore_dirs = arguments.get("ignore_dirs")
        force_reindex = arguments.get("force_reindex", False)

        if not repo_url:
            return [TextContent(
                type="text",
                text="Error: repo_url is required"
            )]

        try:
            rag = self._initialize_rag()

            # Run indexing in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: rag.index_repository(
                    repo_url=repo_url,
                    include_extensions=include_extensions,
                    ignore_dirs=ignore_dirs,
                    force_reindex=force_reindex
                )
            )

            if result.get("success"):
                message = (
                    f"✅ Successfully indexed repository!\n\n"
                    f"Repository: {result['repo_name']}\n"
                    f"Collection: {result['collection_name']}\n"
                    f"Documents indexed: {result.get('document_count', 0)}\n"
                    f"Chunks created: {result.get('chunk_count', 0)}\n\n"
                    f"You can now query this repository using the query_repository tool "
                    f"with collection_name: {result['collection_name']}"
                )
            else:
                message = f"❌ Failed to index repository: {result.get('error', 'Unknown error')}"

            return [TextContent(type="text", text=message)]

        except Exception as e:
            logger.error(f"Error indexing repository: {e}", exc_info=True)
            return [TextContent(
                type="text",
                text=f"Error indexing repository: {str(e)}"
            )]

    async def _query_repository(self, arguments: dict) -> list[TextContent]:
        """Query an indexed repository."""
        collection_name = arguments.get("collection_name")
        question = arguments.get("question")
        max_results = arguments.get("max_results", 5)

        if not collection_name or not question:
            return [TextContent(
                type="text",
                text="Error: collection_name and question are required"
            )]

        try:
            rag = self._initialize_rag()

            # Run query in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: rag.query_repository(
                    collection_name=collection_name,
                    question=question,
                    max_results=max_results
                )
            )

            if result.get("success"):
                output_lines = [
                    f"🔍 Query: {result['question']}",
                    f"📁 Repository: {result['repository']}",
                    f"📊 Sources found: {result['total_sources']}",
                    "",
                    "📝 Answer:",
                    result['answer'],
                    "",
                    "📋 Citations:"
                ]

                for citation in result.get('citations', []):
                    output_lines.append(f"\n[{citation['source_id']}] {citation['file_path']}")
                    output_lines.append(f"└─ {citation['snippet']}")

                message = "\n".join(output_lines)
            else:
                message = f"❌ Query failed: {result.get('error', 'Unknown error')}"

            return [TextContent(type="text", text=message)]

        except Exception as e:
            logger.error(f"Error querying repository: {e}", exc_info=True)
            return [TextContent(
                type="text",
                text=f"Error querying repository: {str(e)}"
            )]

    async def _list_repositories(self, arguments: dict) -> list[TextContent]:
        """List all indexed repositories."""
        try:
            rag = self._initialize_rag()
            repositories = rag.list_repositories()

            if not repositories:
                message = (
                    "📂 No Git repositories have been indexed yet.\n\n"
                    "Use the index_repository tool to index a repository first."
                )
            else:
                output_lines = ["📚 Indexed Git Repositories:", ""]

                for repo in repositories:
                    output_lines.extend([
                        f"📁 {repo['repo_name']}",
                        f"   Collection: {repo['collection_name']}",
                        f"   URL: {repo['repo_url']}",
                        f"   Files: {repo['document_count']} | Chunks: {repo['chunk_count']}",
                        ""
                    ])

                output_lines.append(
                    "💡 Use query_repository with the collection name to ask questions about any repository."
                )

                message = "\n".join(output_lines)

            return [TextContent(type="text", text=message)]

        except Exception as e:
            logger.error(f"Error listing repositories: {e}", exc_info=True)
            return [TextContent(
                type="text",
                text=f"Error listing repositories: {str(e)}"
            )]

    async def run(self):
        """Run the MCP server."""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Main entry point for the MCP server."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create and run server
    server = GitRAGServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
