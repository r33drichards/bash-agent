import os
import subprocess
import argparse
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import uuid
import threading
from datetime import datetime
import time
import tempfile
import psutil
import base64
import asyncio
from typing import Optional
from contextlib import AsyncExitStack

import anthropic
from anthropic import RateLimitError, APIError
import sqlite3
import json
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output
import io
import contextlib

# MCP imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from flask import Flask, render_template, request, jsonify, session, send_file, abort
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from werkzeug.exceptions import NotFound, Forbidden
from urllib.parse import unquote
from pathlib import Path
import mimetypes
import zipfile
import shutil

from memory import MemoryManager
from todos import TodoManager
from github_rag import GitHubRAG

# Import tool definitions and implementations
from tools.bash_tool import bash_tool, execute_bash
from tools.sqlite_tool import sqlite_tool, execute_sqlite
from tools.ipython_tool import ipython_tool, execute_ipython

from tools.todo_tools import (
    create_todo_tool,
    update_todo_tool,
    list_todos_tool,
    search_todos_tool,
    get_todo_tool,
    delete_todo_tool,
    get_todo_stats_tool,
    create_todo,
    update_todo,
    list_todos,
    search_todos,
    get_todo,
    delete_todo,
    get_todo_stats,
)
from tools.github_rag_tools import (
    github_rag_index_tool,
    github_rag_query_tool,
    github_rag_list_tool,
    github_rag_index,
    github_rag_query,
    github_rag_list,
)


# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(script_dir, "templates")

app = Flask(__name__, template_folder=template_dir)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global sessions store
sessions = {}


def save_conversation_history(session_id):
    """Save conversation history to JSON file in metadata directory"""
    if not app.config.get("METADATA_DIR"):
        return

    if session_id not in sessions:
        return

    history = sessions[session_id]["conversation_history"]
    if not history:
        return

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_{session_id[:8]}_{timestamp}.json"
    filepath = os.path.join(app.config["METADATA_DIR"], filename)

    # Save conversation data
    conversation_data = {
        "session_id": session_id,
        "started_at": sessions[session_id]["connected_at"].isoformat(),
        "ended_at": datetime.now().isoformat(),
        "history": history,
    }

    try:
        with open(filepath, "w") as f:
            json.dump(conversation_data, f, indent=2)
        print(f"Conversation history saved to: {filepath}")
    except Exception as e:
        print(f"Error saving conversation history: {e}")


def load_conversation_history():
    """Load all conversation history files from metadata directory"""
    if not app.config.get("METADATA_DIR"):
        return []

    if not os.path.exists(app.config["METADATA_DIR"]):
        return []

    conversations = []
    try:
        for filename in os.listdir(app.config["METADATA_DIR"]):
            if filename.startswith("conversation_") and filename.endswith(".json"):
                filepath = os.path.join(app.config["METADATA_DIR"], filename)
                with open(filepath, "r") as f:
                    conversation_data = json.load(f)
                    conversations.append(conversation_data)

        # Sort by started_at timestamp
        conversations.sort(key=lambda x: x["started_at"], reverse=True)

    except Exception as e:
        print(f"Error loading conversation history: {e}")

    return conversations


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

    # Store global config
    app.config["AUTO_CONFIRM"] = args.auto_confirm
    app.config["WORKING_DIR"] = args.working_dir
    app.config["METADATA_DIR"] = args.metadata_dir
    app.config["SYSTEM_PROMPT"] = args.system_prompt
    app.config["MCP_CONFIG"] = mcp_config_path

    # Change working directory if specified
    if args.working_dir:
        if os.path.exists(args.working_dir):
            os.chdir(args.working_dir)
            print(f"Working directory changed to: {args.working_dir}")
        else:
            print(f"Warning: Working directory {args.working_dir} does not exist")
            return

    # Set file browser root path after working directory is established
    app.config["FILE_BROWSER_ROOT"] = app.config["WORKING_DIR"]
    print(f"File browser root path: {app.config['FILE_BROWSER_ROOT']}")
    print(
        f"File browser access is restricted to: {app.config['FILE_BROWSER_ROOT']} and subdirectories only"
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

    socketio.run(
        app, host=args.host, port=args.port, debug=True, allow_unsafe_werkzeug=True
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/conversation-history")
def get_conversation_history():
    """API endpoint to get conversation history"""
    history = load_conversation_history()
    return jsonify(history)


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """API endpoint to handle file uploads and return content"""
    print("=== UPLOAD ENDPOINT CALLED ===")
    print(f"Request files: {list(request.files.keys())}")

    if "files" not in request.files and "file" not in request.files:
        print("ERROR: No files found in request")
        return jsonify({"success": False, "error": "No file provided"}), 400

    # Handle both single and multiple file uploads
    files = (
        request.files.getlist("files")
        if "files" in request.files
        else [request.files["file"]]
    )
    print(f"Processing {len(files)} files")
    results = []

    for i, file in enumerate(files):
        print(f"Processing file {i + 1}: {file.filename}")
        if file.filename == "":
            print("  Skipping empty filename")
            continue

        try:
            # Create temp file to store upload
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=f"_{file.filename}"
            ) as temp_file:
                file.save(temp_file.name)
                temp_path = temp_file.name

            # Check if it's an image
            file_ext = (
                file.filename.lower().split(".")[-1] if "." in file.filename else ""
            )
            is_image = file_ext in ["png", "jpg", "jpeg", "gif", "bmp", "webp"]
            print(f"  File extension: {file_ext}, is_image: {is_image}")

            # Read file content
            try:
                # Try to read as text first
                with open(temp_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    file_type = "text"
                    # For small text files, include content directly
                    if len(content) < 10000:  # 10KB limit for direct content
                        os.unlink(temp_path)
                        print(f"  Read small text content: {len(content)} chars")
                        results.append(
                            {
                                "name": file.filename,
                                "content": content,
                                "type": file_type,
                                "size": len(content),
                            }
                        )
                        continue
            except UnicodeDecodeError:
                # Binary file
                if is_image:
                    file_type = "image"
                else:
                    file_type = "binary"

            # For large files or binary files, store them temporarily and return a file ID
            file_id = str(uuid.uuid4())

            # Store file info
            uploaded_files[file_id] = {
                "path": temp_path,
                "filename": file.filename,
                "type": file_type,
                "uploaded_at": datetime.now(),
            }

            # Get file size
            file_size = os.path.getsize(temp_path)
            print(
                f"  Stored large/binary file with ID: {file_id}, size: {file_size} bytes"
            )

            results.append(
                {
                    "name": file.filename,
                    "file_id": file_id,
                    "type": file_type,
                    "size": file_size,
                }
            )

        except Exception as e:
            print(f"  Error processing file: {e}")
            results.append({"name": file.filename, "error": str(e)})

    if not results:
        return jsonify({"success": False, "error": "No valid files uploaded"}), 400

    return jsonify({"success": True, "files": results})


def get_file_content_by_id(file_id: str) -> dict:
    """Get file content by file ID."""
    if file_id not in uploaded_files:
        return {"error": "File not found"}

    file_info = uploaded_files[file_id]

    try:
        if file_info["type"] == "text":
            with open(file_info["path"], "r", encoding="utf-8") as f:
                content = f.read()
        else:
            # For binary/image files, read as base64
            with open(file_info["path"], "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")

        return {
            "name": file_info["filename"],
            "content": content,
            "type": file_info["type"],
            "size": len(content),
        }

    except Exception as e:
        return {"error": str(e)}


@app.route("/api/files")
def list_files():
    """List files and directories at given path"""
    current_root = app.config.get("FILE_BROWSER_ROOT", os.getcwd())
    path = request.args.get("path", current_root)
    path = unquote(path) if path else current_root

    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404

    if not os.path.isdir(path):
        return jsonify({"error": "Path is not a directory"}), 400

    try:
        items = []
        for item_name in sorted(os.listdir(path)):
            item_path = os.path.join(path, item_name)

            file_info = get_file_info(item_path)
            if file_info:
                file_info["icon"] = get_file_icon(file_info)
                file_info["size_formatted"] = format_file_size(file_info["size"])
                items.append(file_info)

        # Sort: directories first, then files
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        return jsonify(
            {
                "success": True,
                "path": path,
                "parent": os.path.dirname(path)
                if path != app.config.get("FILE_BROWSER_ROOT", os.getcwd())
                else None,
                "items": items,
            }
        )

    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download_file():
    """Download a file"""
    file_path = request.args.get("path")
    if not file_path:
        return jsonify({"error": "No path specified"}), 400

    file_path = unquote(file_path)

    # Security checks
    if not is_safe_path(file_path) or is_blocked_path(file_path):
        return jsonify({"error": "Access denied"}), 403

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    if os.path.isdir(file_path):
        # Create a zip file for directories
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        try:
            with zipfile.ZipFile(temp_file.name, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(file_path):
                    # Filter out blocked directories
                    dirs[:] = [
                        d for d in dirs if not is_blocked_path(os.path.join(root, d))
                    ]

                    for file in files:
                        full_path = os.path.join(root, file)
                        if not is_blocked_path(full_path):
                            arc_path = os.path.relpath(full_path, file_path)
                            zipf.write(full_path, arc_path)

            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=f"{os.path.basename(file_path)}.zip",
                mimetype="application/zip",
            )
        except Exception as e:
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
            return jsonify({"error": str(e)}), 500
    else:
        # Send individual file
        try:
            return send_file(
                file_path, as_attachment=True, download_name=os.path.basename(file_path)
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/preview")
def preview_file():
    """Preview file content"""
    file_path = request.args.get("path")
    if not file_path:
        return jsonify({"error": "No path specified"}), 400

    file_path = unquote(file_path)

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({"error": "File not found"}), 404

    file_info = get_file_info(file_path)
    if not file_info:
        return jsonify({"error": "Cannot read file info"}), 500

    try:
        ext = file_info["extension"]
        mime_type = file_info["mime_type"]

        # Text files
        if ext in TEXT_EXTENSIONS or mime_type.startswith("text/"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(50000)  # Limit to first 50KB
                return jsonify(
                    {
                        "success": True,
                        "type": "text",
                        "content": content,
                        "truncated": len(content) == 50000,
                        "file_info": file_info,
                    }
                )

        # Images
        elif ext in IMAGE_EXTENSIONS:
            with open(file_path, "rb") as f:
                content = f.read(2 * 1024 * 1024)  # Limit to 2MB
                base64_content = base64.b64encode(content).decode("utf-8")
                return jsonify(
                    {
                        "success": True,
                        "type": "image",
                        "content": f"data:{mime_type};base64,{base64_content}",
                        "file_info": file_info,
                    }
                )

        # Binary files - just show file info
        else:
            return jsonify(
                {
                    "success": True,
                    "type": "binary",
                    "message": "Binary file - preview not available",
                    "file_info": file_info,
                }
            )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/create_folder", methods=["POST"])
def create_folder():
    """Create a new folder"""
    data = request.get_json()
    parent_path = data.get(
        "parent_path", app.config.get("FILE_BROWSER_ROOT", os.getcwd())
    )
    folder_name = data.get("folder_name", "").strip()

    if not folder_name:
        return jsonify({"error": "Folder name required"}), 400

    parent_path = unquote(parent_path)

    # Security checks

    folder_name = secure_filename(folder_name)
    folder_path = os.path.join(parent_path, folder_name)

    if os.path.exists(folder_path):
        return jsonify({"error": "Folder already exists"}), 409

    try:
        os.makedirs(folder_path)
        file_info = get_file_info(folder_path)
        if file_info:
            file_info["icon"] = get_file_icon(file_info)
            file_info["size_formatted"] = format_file_size(file_info["size"])

        return jsonify({"success": True, "folder": file_info})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/delete", methods=["DELETE"])
def delete_item():
    """Delete a file or directory"""
    item_path = request.args.get("path")
    if not item_path:
        return jsonify({"error": "No path specified"}), 400

    item_path = unquote(item_path)

    if not os.path.exists(item_path):
        return jsonify({"error": "Item not found"}), 404

    # Don't allow deletion of root path
    if os.path.abspath(item_path) == os.path.abspath(
        app.config.get("FILE_BROWSER_ROOT", os.getcwd())
    ):
        return jsonify({"error": "Cannot delete root directory"}), 403

    try:
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload-to-path", methods=["POST"])
def upload_to_path():
    """Upload files to a specific directory"""
    target_path = request.form.get(
        "path", app.config.get("FILE_BROWSER_ROOT", os.getcwd())
    )
    target_path = unquote(target_path)

    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        return jsonify({"error": "Invalid target directory"}), 400

    if "files" not in request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = request.files.getlist("files")
    uploaded_files_result = []
    errors = []

    for file in files:
        if file.filename == "":
            continue

        try:
            filename = secure_filename(file.filename)
            file_path = os.path.join(target_path, filename)

            # Handle filename conflicts
            counter = 1
            base_name, ext = os.path.splitext(filename)
            while os.path.exists(file_path):
                new_filename = f"{base_name}_{counter}{ext}"
                file_path = os.path.join(target_path, new_filename)
                counter += 1

            file.save(file_path)
            file_info = get_file_info(file_path)
            if file_info:
                file_info["icon"] = get_file_icon(file_info)
                file_info["size_formatted"] = format_file_size(file_info["size"])
                uploaded_files_result.append(file_info)

        except Exception as e:
            errors.append(f"Failed to upload {file.filename}: {str(e)}")

    return jsonify(
        {
            "success": len(uploaded_files_result) > 0,
            "uploaded_files": uploaded_files_result,
            "errors": errors,
        }
    )


def cleanup_old_files():
    """Clean up files older than 1 hour."""
    current_time = datetime.now()
    files_to_remove = []

    for file_id, file_info in uploaded_files.items():
        if (current_time - file_info["uploaded_at"]).seconds > 3600:  # 1 hour
            files_to_remove.append(file_id)

    for file_id in files_to_remove:
        file_info = uploaded_files[file_id]
        try:
            if os.path.exists(file_info["path"]):
                os.unlink(file_info["path"])
        except Exception:
            pass
        del uploaded_files[file_id]


@socketio.on("connect")
def handle_connect(auth=None):
    session_id = str(uuid.uuid4())
    join_room(session_id)
    session["session_id"] = session_id

    # Always initialize MCP client (with default config if none provided)
    mcp_config_path = app.config.get("MCP_CONFIG")
    print(f"DEBUG: MCP_CONFIG in app.config: {mcp_config_path}")
    print(
        f"DEBUG: Creating MCP client (will use default config if no user config provided)"
    )
    mcp_client = MCPClient()

    # Initialize session first (without LLM)
    sessions[session_id] = {
        "auto_confirm": app.config["AUTO_CONFIRM"],
        "connected_at": datetime.now(),
        "conversation_history": [],
        "memory_manager": MemoryManager(),
        "todo_manager": TodoManager(),
        "mcp_client": mcp_client,
        "mcp_initialized": False,
    }

    # Now initialize LLM with the session context available
    sessions[session_id]["llm"] = LLM(
        "claude-3-7-sonnet-latest", session_id, mcp_client
    )

    # Always initialize MCP client (will use default config if no user config)
    if mcp_client:

        def run_mcp_init():
            asyncio.run(initialize_mcp_client(session_id))

        # Run MCP initialization in a separate thread
        mcp_thread = threading.Thread(target=run_mcp_init, daemon=True)
        mcp_thread.start()
        print(f"Starting MCP initialization for session {session_id}")

    emit("session_started", {"session_id": session_id})
    emit(
        "message",
        {
            "type": "system",
            "content": "Connected to Claude Code Agent. Type your message to start... Initializing MCP servers...",
            "timestamp": datetime.now().isoformat(),
        },
    )

    # Send conversation history if available
    history = load_conversation_history()
    if history:
        emit("conversation_history", history)


@socketio.on("disconnect")
def handle_disconnect():
    session_id = session.get("session_id")
    if session_id in sessions:
        # Save conversation history before cleanup
        save_conversation_history(session_id)
        del sessions[session_id]
    leave_room(session_id)


@socketio.on("user_message")
def handle_user_message(data):
    print(f"=== USER_MESSAGE EVENT RECEIVED ===")
    print(f"Raw data received: {data}")

    session_id = session.get("session_id")
    print(f"Session ID: {session_id}")

    if session_id not in sessions:
        print(f"ERROR: Session {session_id} not found in sessions")
        emit("error", {"message": "Session not found"})
        return

    user_input = data.get("message", "").strip()
    print(f"User input: '{user_input}'")

    if not user_input:
        print("ERROR: No user input provided")
        return

    # Clean up old uploaded files periodically
    cleanup_old_files()

    # Get attached files and resolve content for LLM processing
    attached_files = data.get("files", [])
    print(f"Attached files received: {len(attached_files)} files")

    # Process files - resolve file_id references to actual content
    resolved_files = []
    for i, file_info in enumerate(attached_files):
        print(
            f"  File {i + 1}: {file_info.get('name', 'unknown')} - type: {file_info.get('type', 'unknown')}"
        )

        if "content" in file_info:
            # Small file with direct content
            resolved_files.append(file_info)
            print(f"    Direct content: {len(str(file_info.get('content', '')))} chars")
        elif "file_id" in file_info:
            # Large file stored with file_id - retrieve content
            file_data = get_file_content_by_id(file_info["file_id"])
            if "error" in file_data:
                print(f"    Error loading file: {file_data['error']}")
                # Add error info
                resolved_files.append(
                    {
                        "name": file_info["name"],
                        "content": f"[Error loading file: {file_data['error']}]",
                        "type": "error",
                    }
                )
            else:
                print(
                    f"    Retrieved content: {len(str(file_data.get('content', '')))} chars"
                )
                resolved_files.append(
                    {
                        "name": file_data["name"],
                        "content": file_data["content"],
                        "type": file_data["type"],
                    }
                )

    # Process files and generate summaries once
    llm_message = user_input
    display_message = user_input
    history_message = user_input

    print("Building messages...")
    if resolved_files:
        print(f"Processing {len(resolved_files)} resolved files")
        # Check session still exists before accessing LLM for file processing
        if session_id not in sessions:
            print(f"ERROR: Session {session_id} was removed before file processing")
            emit("error", {"message": "Session expired during file processing"})
            return
        llm = sessions[session_id]["llm"]

        for file_info in resolved_files:
            if file_info.get("type") == "image":
                print(f"  Summarizing image: {file_info['name']}")
                # Generate image summary once
                image_summary = llm.summarize_image(
                    file_info["content"], file_info["name"]
                )

                # Add to LLM message (for processing)
                llm_message += (
                    f"\n\n[Image Description for {file_info['name']}]:\n{image_summary}"
                )

                # Add to display message (clean reference)
                display_message += f"\n\n[Image: {file_info['name']}]"

                # Add to history message (with description)
                history_message += (
                    f"\n\n[Image: {file_info['name']}]\nDescription: {image_summary}"
                )
            else:
                print(f"  Adding file: {file_info['name']}")
                file_content = f"\n\n--- File: {file_info['name']} ---\n{file_info['content']}\n--- End of {file_info['name']} ---"

                # Add to all messages (same content for text files)
                llm_message += file_content
                display_message += file_content
                history_message += file_content

    # Echo user message (clean version for display)
    user_message_display = {
        "type": "user",
        "content": display_message,
        "timestamp": datetime.now().isoformat(),
    }
    print(f"Emitting user message: {user_message_display}")
    emit("message", user_message_display)

    # Store in conversation history (with descriptions)
    user_message_history = {
        "type": "user",
        "content": history_message,
        "timestamp": datetime.now().isoformat(),
    }

    # Double-check session still exists before accessing
    if session_id not in sessions:
        print(
            f"ERROR: Session {session_id} was removed before storing conversation history"
        )
        emit("error", {"message": "Session expired"})
        return

    sessions[session_id]["conversation_history"].append(user_message_history)
    print(f"Added message to conversation history")

    # Process with LLM
    print(f"Starting LLM processing...")
    try:
        # Double-check session still exists before accessing LLM components
        if session_id not in sessions:
            print(f"ERROR: Session {session_id} was removed before LLM processing")
            emit("error", {"message": "Session expired during processing"})
            return

        session_data = sessions[
            session_id
        ]  # Get session data once to avoid multiple lookups
        llm = session_data["llm"]
        auto_confirm = session_data["auto_confirm"]
        memory_manager = session_data["memory_manager"]
        print(
            f"Retrieved session components: llm={llm is not None}, auto_confirm={auto_confirm}"
        )

        # Load relevant memories as context
        relevant_memories = memory_manager.get_memory_context(
            user_input, max_memories=3
        )

        # Load active todos as context
        todo_manager = session_data["todo_manager"]
        active_todos_summary = todo_manager.get_active_todos_summary()

        # Load GitHub RAG repositories context
        github_rag_context = ""
        try:
            if "github_rag" in session_data:
                github_rag = session_data["github_rag"]
                github_rag_context = github_rag.get_repository_memory_context()
        except Exception:
            pass

        # Prepare message with context
        context_parts = []

        if relevant_memories != "No relevant memories found.":
            context_parts.append(relevant_memories)

        if active_todos_summary != "No active todos.":
            context_parts.append(active_todos_summary)

        if (
            github_rag_context
            and github_rag_context
            != "No GitHub repositories have been indexed for RAG queries."
        ):
            context_parts.append(github_rag_context)

        if context_parts:
            context_msg = (
                "\n\n".join(context_parts) + f"\n\n=== USER MESSAGE ===\n{llm_message}"
            )
            msg = [{"type": "text", "text": context_msg}]
        else:
            msg = [{"type": "text", "text": llm_message}]

        print(
            f"Final message to LLM: {msg[0]['text'][:200]}..."
            if len(msg[0]["text"]) > 200
            else f"Final message to LLM: {msg[0]['text']}"
        )
        print("Calling LLM with streaming...")

        # Define streaming callback
        def stream_callback(chunk, stream_type):
            emit(
                "message_chunk",
                {
                    "type": "agent",
                    "chunk": chunk,
                    "stream_type": stream_type,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        # Call LLM with streaming
        output, tool_calls = llm(msg, stream_callback=stream_callback)
        print(
            f"LLM response received: {len(output)} chars, {len(tool_calls) if tool_calls else 0} tool calls"
        )

        # Send final agent response (for history)
        agent_message = {
            "type": "agent",
            "content": output,
            "timestamp": datetime.now().isoformat(),
        }
        emit("message_complete", agent_message)

        # Store in conversation history - check session still exists
        if session_id in sessions:
            sessions[session_id]["conversation_history"].append(agent_message)
        else:
            print(
                f"ERROR: Session {session_id} was removed before storing agent response"
            )

        # Handle tool calls
        if tool_calls:
            for tool_call in tool_calls:
                handle_tool_call_web(tool_call, session_id, auto_confirm)

    except Exception as e:
        emit(
            "message",
            {
                "type": "error",
                "content": f"Error: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            },
        )


@socketio.on("tool_confirm")
def handle_tool_confirm(data):
    session_id = session.get("session_id")
    if session_id not in sessions:
        emit("error", {"message": "Session not found"})
        return

    confirmed = data.get("confirmed", False)

    if confirmed:
        # Execute the tool call
        tool_call = data.get("tool_call")
        if tool_call:
            execute_tool_call_web(tool_call, session_id)
    else:
        # Handle tool cancellation with proper tool_result
        tool_call = data.get("tool_call")
        rejection_reason = data.get("rejection_reason", "")

        if tool_call:
            # Create a tool_result for the cancelled tool
            cancellation_message = "Tool execution cancelled by user."
            if rejection_reason:
                cancellation_message += f" Reason: {rejection_reason}"

            tool_result = {
                "type": "tool_result",
                "tool_use_id": tool_call["id"],
                "content": [{"type": "text", "text": f"Error: {cancellation_message}"}],
            }

            # Send cancellation message to user
            emit(
                "message",
                {
                    "type": "system",
                    "content": cancellation_message,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            # Send tool_result back to LLM to continue conversation
            llm = sessions[session_id]["llm"]
            output, new_tool_calls = llm([tool_result])

            # Validate message structure after tool result processing
            if hasattr(llm, "_validate_message_structure"):
                llm._validate_message_structure(skip_active_tools=False)

            # Send agent response
            agent_message = {
                "type": "agent",
                "content": output,
                "timestamp": datetime.now().isoformat(),
            }
            emit("message", agent_message, room=session_id)

            # Store in conversation history
            sessions[session_id]["conversation_history"].append(agent_message)

            # Handle any new tool calls
            if new_tool_calls:
                for new_tool_call in new_tool_calls:
                    handle_tool_call_web(
                        new_tool_call, session_id, sessions[session_id]["auto_confirm"]
                    )
        else:
            # Fallback if no tool_call data
            emit(
                "message",
                {
                    "type": "system",
                    "content": "Tool execution cancelled by user.",
                    "timestamp": datetime.now().isoformat(),
                },
            )


@socketio.on("update_auto_confirm")
def handle_update_auto_confirm(data):
    session_id = session.get("session_id")
    if session_id not in sessions:
        emit("error", {"message": "Session not found"})
        return

    enabled = data.get("enabled", False)
    sessions[session_id]["auto_confirm"] = enabled

    # Send confirmation message
    status = "enabled" if enabled else "disabled"
    emit(
        "message",
        {
            "type": "system",
            "content": f"Auto-confirm {status}.",
            "timestamp": datetime.now().isoformat(),
        },
    )


@socketio.on("get_auto_confirm_state")
def handle_get_auto_confirm_state():
    session_id = session.get("session_id")
    if session_id not in sessions:
        emit("error", {"message": "Session not found"})
        return

    enabled = sessions[session_id]["auto_confirm"]
    emit("auto_confirm_state", {"enabled": enabled})


def handle_tool_call_web(tool_call, session_id, auto_confirm):
    """Handle tool call in web context"""
    if auto_confirm:
        execute_tool_call_web(tool_call, session_id)
    else:
        # Send confirmation request
        emit(
            "tool_confirmation",
            {
                "tool_call_id": tool_call["id"],
                "tool_name": tool_call["name"],
                "tool_input": tool_call["input"],
                "tool_call": tool_call,
            },
            room=session_id,
        )


async def initialize_mcp_client(session_id):
    """Initialize MCP client for the session"""
    try:
        if session_id not in sessions:
            return

        session_data = sessions[session_id]
        mcp_client = session_data.get("mcp_client")

        if not mcp_client:
            return

        config_path = app.config.get("MCP_CONFIG")
        # Always try to load config - load_config_and_connect handles None gracefully
        # and will load the default config if no user config is provided

        if config_path:
            print(f"DEBUG: About to load MCP config from: {config_path}")
            print(f"DEBUG: Current working directory: {os.getcwd()}")
            print(f"DEBUG: Config file exists: {os.path.exists(config_path)}")
        else:
            print("DEBUG: No user MCP config provided, will load default config")

        await mcp_client.load_config_and_connect(config_path)
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
        socketio.emit(
            "tool_result",
            {
                "tool_use_id": tool_call["id"],
                "result": f"Error executing MCP tool: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            },
            room=session_id,
        )


def execute_tool_call_web(tool_call, session_id):
    """Execute tool call and emit results"""
    try:
        print(f"DEBUG: execute_tool_call_web received tool_call: {tool_call}")
        print(
            f"DEBUG: tool_call type: {type(tool_call)}, name: {tool_call.get('name')}, input: {tool_call.get('input')}"
        )

        # Send detailed tool execution info
        tool_info = {
            "type": "tool_execution",
            "tool_name": tool_call["name"],
            "tool_input": tool_call.get("input", {}),
            "timestamp": datetime.now().isoformat(),
        }

        # Add the actual code/command being executed
        tool_input = tool_call.get("input", {})
        if tool_call["name"] == "bash":
            tool_info["code"] = tool_input.get("command", "No command provided")
            tool_info["language"] = "bash"
            tool_info["timeout"] = tool_input.get("timeout", 30)
            tool_info["stream_output"] = tool_input.get("stream_output", False)
        elif tool_call["name"] == "ipython":
            tool_info["code"] = tool_input.get("code", "No code provided")
            tool_info["language"] = "python"
        elif tool_call["name"] == "sqlite":
            tool_info["code"] = tool_input.get("query", "No query provided")
            tool_info["language"] = "sql"

        emit("tool_execution_start", tool_info, room=session_id)

        # Check if this is an MCP tool and handle async execution
        is_mcp_tool = False
        if session_id in sessions:
            session_data = sessions[session_id]
            mcp_client = session_data.get("mcp_client")
            if mcp_client and hasattr(mcp_client, "available_tools"):
                # Check if tool name matches any MCP tool
                is_mcp_tool = any(
                    tool["name"] == tool_call["name"]
                    for tool in mcp_client.available_tools
                )
                print(
                    f"DEBUG: Tool '{tool_call['name']}' - MCP tool check: {is_mcp_tool}"
                )

        if is_mcp_tool and session_id in sessions:
            session_data = sessions[session_id]
            if session_data.get("mcp_client"):
                # Initialize MCP client if not done yet
                if not session_data.get("mcp_initialized"):
                    result = {
                        "type": "tool_result",
                        "tool_use_id": tool_call["id"],
                        "content": [
                            {
                                "type": "text",
                                "text": "MCP client is still initializing. Please try again in a moment.",
                            }
                        ],
                    }
                else:
                    # MCP client is initialized, try to call the tool asynchronously
                    try:

                        def run_mcp_tool():
                            asyncio.run(handle_mcp_tool_call(session_id, tool_call))

                        # Run MCP tool call in a separate thread
                        mcp_tool_thread = threading.Thread(
                            target=run_mcp_tool, daemon=True
                        )
                        mcp_tool_thread.start()

                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": [
                                {
                                    "type": "text",
                                    "text": "MCP tool executed. Results will be emitted separately.",
                                }
                            ],
                        }
                    except Exception as e:
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Error executing MCP tool: {str(e)}",
                                }
                            ],
                        }
            else:
                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": [{"type": "text", "text": "MCP client not configured"}],
                }
        else:
            # Execute the tool normally
            print(
                f"DEBUG: Executing standard tool: {tool_call['name']} with input: {tool_call.get('input')}"
            )
            result = execute_tool_call(tool_call)

        # Extract the result content
        result_content = ""
        plots = []
        if result and "content" in result and result["content"]:
            result_content = (
                result["content"][0]["text"]
                if result["content"][0]["type"] == "text"
                else str(result["content"])
            )

        # Extract plots if available (from IPython execution)
        if result and "plots" in result:
            plots = result["plots"]

        # Send detailed execution result
        result_data = {
            "type": "tool_result",
            "tool_name": tool_call["name"],
            "result": result_content,
            "timestamp": datetime.now().isoformat(),
        }

        if plots:
            result_data["plots"] = plots

        emit("tool_execution_result", result_data, room=session_id)

        # Send result back to LLM
        llm = sessions[session_id]["llm"]
        output, new_tool_calls = llm([result])

        # Validate message structure after tool result processing
        if hasattr(llm, "_validate_message_structure"):
            llm._validate_message_structure(skip_active_tools=False)

        # Send agent response
        agent_message = {
            "type": "agent",
            "content": output,
            "timestamp": datetime.now().isoformat(),
        }
        emit("message", agent_message, room=session_id)

        # Store in conversation history
        sessions[session_id]["conversation_history"].append(agent_message)

        # Handle any new tool calls
        if new_tool_calls:
            for new_tool_call in new_tool_calls:
                handle_tool_call_web(
                    new_tool_call, session_id, sessions[session_id]["auto_confirm"]
                )

    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        print(f"ERROR: Tool execution failed: {str(e)}")
        print(f"ERROR: Full traceback:\n{error_details}")
        emit(
            "message",
            {
                "type": "error",
                "content": f"Tool execution error: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            },
            room=session_id,
        )


def execute_tool_call(tool_call):
    """Execute a tool call and return the result"""
    print(
        f"DEBUG: execute_tool_call received: name={tool_call.get('name')}, input={tool_call.get('input')}"
    )
    if tool_call["name"] == "bash":
        # Add better error handling for input format
        tool_input = tool_call.get("input", {})
        if not isinstance(tool_input, dict):
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text=f"Error: Tool input must be a dictionary, got {type(tool_input)}",
                    )
                ],
            )

        command = tool_input.get("command")
        if not command:
            return dict(
                type="tool_result",
                tool_use_id=tool_call["id"],
                content=[
                    dict(
                        type="text",
                        text="Error: 'command' parameter is required for bash tool",
                    )
                ],
            )

        timeout = tool_input.get("timeout", 30)
        stream_output = tool_input.get("stream_output", False)
        output_text = execute_bash(command, timeout, stream_output)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "sqlite":
        db_path = tool_call["input"]["db_path"]
        query = tool_call["input"]["query"]
        output_json = tool_call["input"].get("output_json")
        print_result = tool_call["input"].get("print_result", False)
        output_text = execute_sqlite(db_path, query, output_json, print_result)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "ipython":
        code = tool_call["input"]["code"]
        print_result = tool_call["input"].get("print_result", False)
        output_text, plots = execute_ipython(code, print_result)
        result = dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
        return result

    elif tool_call["name"] == "create_todo":
        title = tool_call["input"]["title"]
        description = tool_call["input"].get("description", "")
        priority = tool_call["input"].get("priority", "medium")
        project = tool_call["input"].get("project")
        due_date = tool_call["input"].get("due_date")
        tags = tool_call["input"].get("tags")
        estimated_hours = tool_call["input"].get("estimated_hours")
        output_text = create_todo(
            title, description, priority, project, due_date, tags, estimated_hours
        )
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "update_todo":
        todo_id = tool_call["input"]["todo_id"]
        updates = {k: v for k, v in tool_call["input"].items() if k != "todo_id"}
        output_text = update_todo(todo_id, **updates)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "list_todos":
        state = tool_call["input"].get("state")
        priority = tool_call["input"].get("priority")
        project = tool_call["input"].get("project")
        limit = tool_call["input"].get("limit", 20)
        output_text = list_todos(state, priority, project, limit)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )

    elif tool_call["name"] == "search_todos":
        query = tool_call["input"]["query"]
        include_completed = tool_call["input"].get("include_completed", False)
        output_text = search_todos(query, include_completed)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "get_todo":
        todo_id = tool_call["input"]["todo_id"]
        output_text = get_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "delete_todo":
        todo_id = tool_call["input"]["todo_id"]
        output_text = delete_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "get_todo_stats":
        project = tool_call["input"].get("project")
        output_text = get_todo_stats(project)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_index":
        repo_url = tool_call["input"]["repo_url"]
        include_extensions = tool_call["input"].get("include_extensions")
        ignore_dirs = tool_call["input"].get("ignore_dirs")
        output_text = github_rag_index(repo_url, include_extensions, ignore_dirs)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_query":
        collection_name = tool_call["input"]["collection_name"]
        question = tool_call["input"]["question"]
        max_results = tool_call["input"].get("max_results", 5)
        output_text = github_rag_query(collection_name, question, max_results)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    elif tool_call["name"] == "github_rag_list":
        output_text = github_rag_list()
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)],
        )
    else:
        # For now, just return an error for unsupported tools
        # MCP tools should be handled through the web interface with proper async support
        raise Exception(f"Unsupported tool: {tool_call['name']}")


def get_current_session_id():
    """Get the current session ID from Flask session context"""
    from flask import session as flask_session

    return flask_session.get("session_id")


def emit_streaming_output(data, stream_type):
    """Emit streaming output to the web client if available."""
    try:
        from flask import session as flask_session

        session_id = flask_session.get("session_id")
        if session_id:
            emit(
                "streaming_output",
                {
                    "data": data,
                    "stream_type": stream_type,
                    "timestamp": datetime.now().isoformat(),
                },
                room=session_id,
            )
    except:
        pass  # Ignore if not in web context


# File Browser Configuration for Flask routes
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "svg", "webp"}
TEXT_EXTENSIONS = {
    "txt",
    "py",
    "js",
    "html",
    "css",
    "json",
    "xml",
    "md",
    "yml",
    "yaml",
    "ini",
    "cfg",
    "conf",
    "sh",
    "bat",
    "ps1",
}
ARCHIVE_EXTENSIONS = {"zip", "tar", "gz", "rar", "7z"}

# Store uploaded files temporarily by file ID
uploaded_files = {}


def get_file_info(path):
    """Get detailed file information"""
    try:
        stat = os.stat(path)
        return {
            "name": os.path.basename(path),
            "path": path,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "is_dir": os.path.isdir(path),
            "is_file": os.path.isfile(path),
            "extension": Path(path).suffix.lower().lstrip("."),
            "mime_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
        }
    except (OSError, IOError):
        return None


def format_file_size(size):
    """Format file size in human readable format"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def get_file_icon(file_info):
    """Get appropriate icon for file type"""
    if file_info["is_dir"]:
        return "📁"

    ext = file_info["extension"]
    if ext in IMAGE_EXTENSIONS:
        return "🖼️"
    elif ext in ["py"]:
        return "🐍"
    elif ext in ["js", "ts"]:
        return "📄"
    elif ext in ["html", "htm"]:
        return "🌐"
    elif ext in ["css", "scss", "sass"]:
        return "🎨"
    elif ext in ["json", "yaml", "yml", "xml"]:
        return "⚙️"
    elif ext in ["txt", "md", "rst"]:
        return "📝"
    elif ext in ARCHIVE_EXTENSIONS:
        return "📦"
    elif ext in ["pdf"]:
        return "📄"
    elif ext in ["mp3", "wav", "flac", "ogg"]:
        return "🎵"
    elif ext in ["mp4", "avi", "mov", "mkv"]:
        return "🎬"
    else:
        return "📄"


def is_safe_path(path):
    """Check if path is safe (no path traversal)"""
    if not app.config.get("FILE_BROWSER_ROOT"):
        return True

    try:
        abs_path = os.path.abspath(path)
        root_path = os.path.abspath(app.config["FILE_BROWSER_ROOT"])
        return abs_path.startswith(root_path)
    except:
        return False


def is_blocked_path(path):
    """Check if path should be blocked from access"""
    blocked_dirs = {".git", "__pycache__", "node_modules", ".svn", ".hg", "venv", "env"}
    path_parts = Path(path).parts
    return any(part in blocked_dirs for part in path_parts)


def get_current_todo_manager():
    """Get the todo manager for the current session."""
    from flask import session as flask_session

    session_id = flask_session.get("session_id")
    if session_id and session_id in sessions:
        return sessions[session_id]["todo_manager"]
    return TodoManager()  # Fallback to default


def get_current_github_rag():
    """Get the current session's GitHub RAG instance."""
    try:
        from flask import session as flask_session

        session_id = flask_session.get("session_id")
        if session_id and session_id in sessions:
            if "github_rag" not in sessions[session_id]:
                # Initialize GitHub RAG with OpenAI API key
                openai_api_key = os.environ.get("OPENAI_API_KEY")
                if not openai_api_key:
                    raise ValueError("OPENAI_API_KEY environment variable not found")
                sessions[session_id]["github_rag"] = GitHubRAG(openai_api_key)
            return sessions[session_id]["github_rag"]
        else:
            raise Exception("No active session found")
    except Exception as e:
        raise Exception(f"Could not get GitHub RAG instance: {str(e)}")


def github_rag_index(repo_url, include_extensions=None, ignore_dirs=None):
    """Index a GitHub repository for RAG queries."""
    try:
        github_rag = get_current_github_rag()

        # Create progress callback that emits to web client
        def progress_callback(progress_data):
            session_id = get_current_session_id()
            if session_id:
                socketio.emit("rag_index_progress", progress_data, room=session_id)

        result = github_rag.index_repository(
            repo_url=repo_url,
            include_extensions=include_extensions,
            ignore_dirs=ignore_dirs,
            progress_callback=progress_callback,
        )

        if result["success"]:
            # Add to memory for context
            memory_manager = get_current_memory_manager()
            memory_manager.save_memory(
                title=f"GitHub Repository Indexed: {result['repo_name']}",
                content=f"Repository: {repo_url}\nCollection: {result['collection_name']}\nDocuments: {result.get('document_count', 0)}\nChunks: {result.get('chunk_count', 0)}",
                tags=["github_rag", "repository", result["repo_name"]],
            )

            # Refresh system prompt to include the new repository
            session_id = get_current_session_id()
            if session_id and session_id in sessions:
                llm = sessions[session_id]["llm"]
                llm.refresh_system_prompt()

            return f"✅ {result['message']}\n\nRepository: {result['repo_name']}\nCollection: {result['collection_name']}\nDocuments indexed: {result.get('document_count', 0)}\nChunks created: {result.get('chunk_count', 0)}\n\nYou can now query this repository using the github_rag_query tool with collection_name: {result['collection_name']}"
        else:
            return f"❌ Failed to index repository: {result['error']}"

    except Exception as e:
        return f"Error indexing repository: {str(e)}"


def github_rag_query(collection_name, question, max_results=5):
    """Query an indexed GitHub repository."""
    try:
        github_rag = get_current_github_rag()
        result = github_rag.query_repository(
            collection_name=collection_name, question=question, max_results=max_results
        )

        if result["success"]:
            output_lines = [
                f"🔍 Query: {result['question']}",
                f"📁 Repository: {result['repository']}",
                f"📊 Sources found: {result['total_sources']}",
                "",
                "📝 Answer:",
                result["answer"],
                "",
                "📋 Citations:",
            ]

            for citation in result["citations"]:
                output_lines.append(
                    f"\n[{citation['source_id']}] {citation['file_path']}"
                )
                output_lines.append(f"└─ {citation['snippet']}")

            return "\n".join(output_lines)
        else:
            return f"❌ Query failed: {result['error']}"

    except Exception as e:
        return f"Error querying repository: {str(e)}"


def github_rag_list():
    """List all indexed GitHub repositories."""
    try:
        github_rag = get_current_github_rag()
        repositories = github_rag.list_repositories()

        if not repositories:
            return "📂 No GitHub repositories have been indexed yet.\n\nUse the github_rag_index tool to index a repository first."

        output_lines = ["📚 Indexed GitHub Repositories:", ""]

        for repo in repositories:
            output_lines.extend(
                [
                    f"📁 {repo['repo_name']}",
                    f"   Collection: {repo['collection_name']}",
                    f"   URL: {repo['repo_url']}",
                    f"   Files: {repo['document_count']} | Chunks: {repo['chunk_count']}",
                    "",
                ]
            )

        output_lines.append(
            "💡 Use github_rag_query with the collection name to ask questions about any repository."
        )

        return "\n".join(output_lines)

    except Exception as e:
        return f"Error listing repositories: {str(e)}"


class MCPClient:
    """MCP Client for connecting to MCP servers and executing tools"""

    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.servers = {}
        self.available_tools = []
        self.is_initialized = False

    async def load_config_and_connect(self, config_path: str):
        """Load MCP configuration and connect to servers"""
        try:
            print(f"DEBUG: MCPClient trying to open config file: {config_path}")
            print(f"DEBUG: MCPClient current working directory: {os.getcwd()}")

            # Hard-coded default config to ensure filesystem server is always available
            example_config = {
                "mcpServers": {
                    "filesystem": {
                        "command": "mcp-server-filesystem",
                        "args": [app.config.get("WORKING_DIR")],
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


class LLM:
    def __init__(self, model, session_id=None, mcp_client=None):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise ValueError("ANTHROPIC_API_KEY environment variable not found.")
        self.client = anthropic.Anthropic()
        self.model = model
        self.session_id = session_id
        self.mcp_client = mcp_client
        self.messages = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
        self.system_prompt = self._build_system_prompt()
        self.tools = [
            bash_tool,
            sqlite_tool,
            ipython_tool,
            create_todo_tool,
            update_todo_tool,
            list_todos_tool,
            search_todos_tool,
            get_todo_tool,
            delete_todo_tool,
            get_todo_stats_tool,
            github_rag_index_tool,
            github_rag_query_tool,
            github_rag_list_tool,
        ]

        # Add MCP tools if MCP client is available
        if self.mcp_client and self.mcp_client.is_initialized:
            mcp_tools = self.mcp_client.get_tools_for_anthropic()
            self.tools.extend(mcp_tools)

    def _build_system_prompt(self):
        """Build the system prompt dynamically including RAG repository information."""
        base_prompt = ()

        # Add RAG repository information if available
        rag_info = self._get_rag_repositories_info()
        if rag_info:
            base_prompt += rag_info + "\n\n"

        # Add custom system prompt if configured
        if "SYSTEM_PROMPT" in app.config and app.config["SYSTEM_PROMPT"]:
            base_prompt += app.config["SYSTEM_PROMPT"]

        print("SYSTEM PROMPT:", base_prompt)

        return base_prompt

    def _get_rag_repositories_info(self):
        """Get information about available RAG repositories."""
        try:
            if self.session_id and self.session_id in sessions:
                if "github_rag" not in sessions[self.session_id]:
                    # Try to initialize GitHub RAG to check for existing repositories
                    openai_api_key = os.environ.get("OPENAI_API_KEY")
                    if openai_api_key:
                        sessions[self.session_id]["github_rag"] = GitHubRAG(
                            openai_api_key
                        )
                    else:
                        return None

                github_rag = sessions[self.session_id]["github_rag"]
                repositories = github_rag.list_repositories()

                if repositories:
                    rag_info = "INDEXED RAG REPOSITORIES:\n"
                    rag_info += "The following GitHub repositories are available for querying:\n"
                    for repo in repositories:
                        rag_info += f"- {repo['repo_name']} (collection: {repo['collection_name']}) - {repo['document_count']} files, {repo['chunk_count']} chunks\n"
                    rag_info += "Use github_rag_query with the collection name to ask questions about these repositories."
                    return rag_info
        except Exception:
            # Silently ignore errors to avoid breaking initialization
            pass

        return None

    def refresh_system_prompt(self):
        """Refresh the system prompt to include newly indexed repositories."""
        self.system_prompt = self._build_system_prompt()

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _call_anthropic(self, stream=False):
        return self.client.messages.create(
            model=self.model,
            max_tokens=64_000,
            system=self.system_prompt,
            messages=self.messages,
            tools=self.tools,
            stream=stream,
            timeout=600.0,  # 10 minutes timeout for long operations
        )

    def summarize_image(self, image_data, filename):
        """Summarize an image using a separate LLM call to save tokens."""
        print(f"Summarizing image: {filename}")

        # Create a simple client for image summarization
        temp_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Please provide a detailed description of this image ({filename}). Focus on the key visual elements, text content, UI elements, code, diagrams, or any other important details that would be useful for an AI assistant helping with programming tasks.",
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                ],
            }
        ]

        try:
            response = self.client.messages.create(
                model="claude-opus-4-1-20250805",  # Use latest Claude for best image understanding
                max_tokens=1000,
                system="You are an expert at describing images in detail. Provide comprehensive descriptions that would help an AI assistant understand the content.",
                messages=temp_messages,
            )
            summary = response.content[0].text
            print(f"Image summary generated: {len(summary)} chars")
            return summary
        except Exception as e:
            print(f"Error summarizing image: {e}")
            return f"[Image: {filename} - Could not generate summary: {str(e)}]"

    def _call_with_streaming(self, stream_callback):
        """Handle streaming responses."""
        print("Starting streaming response...")

        response_text = ""
        tool_calls = []
        input_tokens = 0
        output_tokens = 0

        try:
            with self._call_anthropic(stream=True) as stream:
                for event in stream:
                    if event.type == "message_start":
                        input_tokens = event.message.usage.input_tokens

                    elif event.type == "content_block_start":
                        if event.content_block.type == "text":
                            pass  # Text block starting
                        elif event.content_block.type == "tool_use":
                            tool_calls.append(
                                {
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input": event.content_block.input,
                                }
                            )

                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            chunk = event.delta.text
                            response_text += chunk
                            # Stream to callback
                            if stream_callback:
                                stream_callback(chunk, "content")
                        elif event.delta.type == "input_json_delta":
                            # Tool input is being streamed
                            pass

                    elif event.type == "message_delta":
                        if hasattr(event.delta, "stop_reason"):
                            print(f"Stream finished: {event.delta.stop_reason}")

                    elif event.type == "message_stop":
                        # Handle different API versions - some have usage directly on event
                        if hasattr(event, "usage") and event.usage:
                            output_tokens = event.usage.output_tokens
                        elif hasattr(event, "message") and hasattr(
                            event.message, "usage"
                        ):
                            output_tokens = event.message.usage.output_tokens

        except Exception as e:
            print(f"Streaming error: {e}")
            raise

        # Update token usage
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_tokens = self.total_input_tokens + self.total_output_tokens

        # Emit token usage update
        if stream_callback:
            try:
                from flask import session as flask_session

                session_id = flask_session.get("session_id")
                if session_id:
                    emit(
                        "token_usage_update",
                        {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_input_tokens": self.total_input_tokens,
                            "total_output_tokens": self.total_output_tokens,
                            "total_tokens": self.total_tokens,
                            "timestamp": datetime.now().isoformat(),
                        },
                        room=session_id,
                    )
            except:
                pass

        # Return response text and tool calls
        return response_text, tool_calls

    def _remove_cache_control(self):
        """Safely remove cache_control from the user message."""
        if not self.messages:
            return

        # Find the most recent user message
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                user_message = self.messages[i]
                if (
                    isinstance(user_message.get("content"), list)
                    and len(user_message["content"]) > 0
                ):
                    last_content = user_message["content"][-1]
                    if (
                        isinstance(last_content, dict)
                        and "cache_control" in last_content
                    ):
                        del last_content["cache_control"]
                        print(f"DEBUG: Removed cache_control from user message")
                break

    def _validate_message_structure(self, skip_active_tools=True):
        """Validate message structure to prevent orphaned tool_result blocks.

        Args:
            skip_active_tools: If True, skip validation if there are recent tool_use blocks
                              that may still be waiting for results.
        """
        if not self.messages:
            return

        print(f"DEBUG: Validating message structure with {len(self.messages)} messages")

        # If skip_active_tools is True, check for recent tool_use blocks without results
        if skip_active_tools and len(self.messages) >= 2:
            last_message = self.messages[-1]
            if last_message.get("role") == "assistant" and isinstance(
                last_message.get("content"), list
            ):
                # Check if last assistant message has tool_use blocks
                has_tool_use = any(
                    (isinstance(c, dict) and c.get("type") == "tool_use")
                    or (hasattr(c, "type") and c.type == "tool_use")
                    for c in last_message["content"]
                )
                if has_tool_use:
                    print(
                        "DEBUG: Skipping validation - recent tool_use blocks may still be active"
                    )
                    return

        # Print all messages for debugging
        for i, msg in enumerate(self.messages):
            print(
                f"DEBUG: Message {i}: role={msg.get('role')}, content_type={type(msg.get('content'))}"
            )
            if isinstance(msg.get("content"), list):
                for j, content in enumerate(msg["content"]):
                    content_type = (
                        content.get("type")
                        if isinstance(content, dict)
                        else getattr(content, "type", "unknown")
                    )
                    if content_type == "tool_use":
                        tool_id = (
                            content.get("id")
                            if isinstance(content, dict)
                            else getattr(content, "id", "unknown")
                        )
                        print(
                            f"DEBUG:   Content {j}: {content_type} with ID: {tool_id}"
                        )
                    elif content_type == "tool_result":
                        tool_use_id = (
                            content.get("tool_use_id")
                            if isinstance(content, dict)
                            else getattr(content, "tool_use_id", "unknown")
                        )
                        print(
                            f"DEBUG:   Content {j}: {content_type} with tool_use_id: {tool_use_id}"
                        )
                    else:
                        print(f"DEBUG:   Content {j}: {content_type}")

        # Check for orphaned tool_result blocks
        for i, message in enumerate(self.messages):
            if message.get("role") == "user" and isinstance(
                message.get("content"), list
            ):
                tool_results = [
                    c for c in message["content"] if c.get("type") == "tool_result"
                ]
                if tool_results:
                    print(
                        f"DEBUG: Found {len(tool_results)} tool_result blocks in message {i}"
                    )

                    # Look for corresponding tool_use blocks in previous assistant messages
                    tool_use_ids = set()

                    # Search backwards for the most recent assistant message with tool_use blocks
                    for j in range(i - 1, -1, -1):
                        prev_message = self.messages[j]
                        print(
                            f"DEBUG: Checking message {j}: role={prev_message.get('role')}"
                        )

                        if prev_message.get("role") == "assistant":
                            prev_content = prev_message.get("content", [])
                            print(
                                f"DEBUG: Assistant message content type: {type(prev_content)}"
                            )
                            if isinstance(prev_content, list):
                                for c in prev_content:
                                    if hasattr(c, "type") and c.type == "tool_use":
                                        tool_id = getattr(c, "id", None)
                                        if tool_id:
                                            tool_use_ids.add(tool_id)
                                            print(
                                                f"DEBUG: Found tool_use with ID: {tool_id}"
                                            )
                                    elif (
                                        isinstance(c, dict)
                                        and c.get("type") == "tool_use"
                                    ):
                                        tool_id = c.get("id")
                                        if tool_id:
                                            tool_use_ids.add(tool_id)
                                            print(
                                                f"DEBUG: Found tool_use with ID: {tool_id}"
                                            )
                            break  # Stop at first assistant message found

                    print(f"DEBUG: All valid tool_use IDs found: {tool_use_ids}")

                    # If no tool_use blocks found, remove ALL tool_result blocks
                    if not tool_use_ids:
                        print(
                            f"DEBUG: No tool_use blocks found - removing ALL {len(tool_results)} tool_result blocks"
                        )
                        original_count = len(message["content"])
                        valid_content = []
                        removed_count = 0
                        for content_block in message["content"]:
                            if content_block.get("type") == "tool_result":
                                print(
                                    f"DEBUG: Removing orphaned tool_result with ID: {content_block.get('tool_use_id')}"
                                )
                                removed_count += 1
                                continue
                            valid_content.append(content_block)
                        message["content"] = valid_content
                        print(
                            f"DEBUG: Removed {removed_count} orphaned tool_results. Content blocks: {original_count} -> {len(valid_content)}"
                        )
                    else:
                        # Remove only orphaned tool_results
                        original_count = len(message["content"])
                        valid_content = []
                        removed_count = 0
                        for content_block in message["content"]:
                            if content_block.get("type") == "tool_result":
                                tool_result_id = content_block.get("tool_use_id")
                                print(
                                    f"DEBUG: Checking tool_result with ID: {tool_result_id}"
                                )
                                if tool_result_id not in tool_use_ids:
                                    print(
                                        f"DEBUG: Removing orphaned tool_result with ID: {tool_result_id}"
                                    )
                                    removed_count += 1
                                    continue
                                else:
                                    print(
                                        f"DEBUG: Keeping valid tool_result with ID: {tool_result_id}"
                                    )
                            valid_content.append(content_block)
                        message["content"] = valid_content
                        print(
                            f"DEBUG: Removed {removed_count} orphaned tool_results. Content blocks: {original_count} -> {len(valid_content)}"
                        )

    def __call__(self, content, stream_callback=None):
        """Main call method with optional streaming support."""
        print(f"DEBUG: LLM.__call__ received content with {len(content)} items:")
        for i, item in enumerate(content):
            item_type = (
                item.get("type")
                if isinstance(item, dict)
                else getattr(item, "type", "unknown")
            )
            print(f"DEBUG:   Item {i}: {item_type}")
            if item_type == "tool_result":
                tool_use_id = (
                    item.get("tool_use_id")
                    if isinstance(item, dict)
                    else getattr(item, "tool_use_id", "unknown")
                )
                print(f"DEBUG:     tool_use_id: {tool_use_id}")

        self.messages.append({"role": "user", "content": content})

        # Add cache control to the last content item if it exists
        user_message = self.messages[-1]
        if user_message.get("content") and len(user_message["content"]) > 0:
            user_message["content"][-1]["cache_control"] = {"type": "ephemeral"}

        # Note: Message validation is moved to after tool execution to prevent interference
        # with active tool calls that haven't received results yet

        try:
            # Use streaming if callback provided
            if stream_callback:
                # Get response from streaming
                response_text, tool_calls = self._call_with_streaming(stream_callback)

                # Build assistant message for streaming response
                assistant_response = {"role": "assistant", "content": []}

                # Add text content if any
                if response_text:
                    assistant_response["content"].append(
                        {"type": "text", "text": response_text}
                    )

                # Add tool_use blocks
                for tool_call in tool_calls:
                    # Create a proper tool_use content block as a dict
                    tool_use_block = {
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["name"],
                        "input": tool_call["input"],
                    }
                    assistant_response["content"].append(tool_use_block)

                # Append assistant message to conversation history
                print(
                    f"DEBUG: Appending streaming assistant response. Messages before: {len(self.messages)}"
                )
                self.messages.append(assistant_response)
                print(f"DEBUG: Messages after: {len(self.messages)}")

                # Clean up cache control from user message
                self._remove_cache_control()

                # Return the expected format
                return response_text, tool_calls
            else:
                response = self._call_anthropic()
        except (RateLimitError, APIError) as e:
            print(f"\nRate limit or API error occurred: {str(e)}")
            raise
        finally:
            # Clean up cache control safely
            self._remove_cache_control()

        # Track token usage
        if hasattr(response, "usage"):
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.total_tokens = self.total_input_tokens + self.total_output_tokens

            # Emit token usage update to web client
            try:
                from flask import session as flask_session

                session_id = flask_session.get("session_id")
                if session_id:
                    emit(
                        "token_usage_update",
                        {
                            "input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens,
                            "total_input_tokens": self.total_input_tokens,
                            "total_output_tokens": self.total_output_tokens,
                            "total_tokens": self.total_tokens,
                            "timestamp": datetime.now().isoformat(),
                        },
                        room=session_id,
                    )
            except:
                pass  # Ignore if not in web context

        assistant_response = {"role": "assistant", "content": []}
        tool_calls = []
        output_text = ""

        for content in response.content:
            if content.type == "text":
                text_content = content.text
                output_text += text_content
                assistant_response["content"].append(
                    {"type": "text", "text": text_content}
                )
                print(
                    f"DEBUG: Adding text content to assistant response: {len(text_content)} chars"
                )
            elif content.type == "tool_use":
                assistant_response["content"].append(content)
                tool_calls.append(
                    {"id": content.id, "name": content.name, "input": content.input}
                )
                print(
                    f"DEBUG: Adding tool_use to assistant response: {content.name} with ID: {content.id}"
                )

        print(
            f"DEBUG: Appending assistant response to messages. Total messages before: {len(self.messages)}"
        )
        print(
            f"DEBUG: Assistant response content blocks: {len(assistant_response['content'])}"
        )
        for i, content in enumerate(assistant_response["content"]):
            content_type = (
                content.get("type")
                if isinstance(content, dict)
                else getattr(content, "type", "unknown")
            )
            print(f"DEBUG:   Assistant content {i}: {content_type}")

        self.messages.append(assistant_response)
        print(
            f"DEBUG: Total messages after adding assistant response: {len(self.messages)}"
        )

        # Validate message structure after assistant response is added, but only if no tools were called
        # (tool results will be added later and we don't want to interfere)
        if not tool_calls:
            self._validate_message_structure(skip_active_tools=False)

        return output_text, tool_calls


if __name__ == "__main__":
    main()
