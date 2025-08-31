import os
import tempfile
import uuid
import base64
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
import mimetypes

from flask import Blueprint, render_template, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename
from werkzeug.exceptions import NotFound, Forbidden
from urllib.parse import unquote

from agent.utils import (
    get_file_info, format_file_size, get_file_icon, is_safe_path, is_blocked_path,
    IMAGE_EXTENSIONS, TEXT_EXTENSIONS, ARCHIVE_EXTENSIONS,
    uploaded_files, get_file_content_by_id
)

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route("/conversation-history")
def get_conversation_history():
    """API endpoint to get conversation history"""
    from agent.conversation import load_conversation_history
    history = load_conversation_history()
    return jsonify(history)


@api_bp.route("/upload", methods=["POST"])
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
            is_image = file_ext in [ext.lower() for ext in IMAGE_EXTENSIONS]
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


@api_bp.route("/files")
def list_files():
    """List files and directories at given path"""
    from flask import current_app
    current_root = current_app.config.get("FILE_BROWSER_ROOT", os.getcwd())
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
                if path != current_app.config.get("FILE_BROWSER_ROOT", os.getcwd())
                else None,
                "items": items,
            }
        )

    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/download")
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


@api_bp.route("/preview")
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


@api_bp.route("/create_folder", methods=["POST"])
def create_folder():
    """Create a new folder"""
    from flask import current_app
    data = request.get_json()
    parent_path = data.get(
        "parent_path", current_app.config.get("FILE_BROWSER_ROOT", os.getcwd())
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


@api_bp.route("/delete", methods=["DELETE"])
def delete_item():
    """Delete a file or directory"""
    from flask import current_app
    item_path = request.args.get("path")
    if not item_path:
        return jsonify({"error": "No path specified"}), 400

    item_path = unquote(item_path)

    if not os.path.exists(item_path):
        return jsonify({"error": "Item not found"}), 404

    # Don't allow deletion of root path
    if os.path.abspath(item_path) == os.path.abspath(
        current_app.config.get("FILE_BROWSER_ROOT", os.getcwd())
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


@api_bp.route("/upload-to-path", methods=["POST"])
def upload_to_path():
    """Upload files to a specific directory"""
    from flask import current_app
    target_path = request.form.get(
        "path", current_app.config.get("FILE_BROWSER_ROOT", os.getcwd())
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


@api_bp.route("/check-api-keys")
def check_api_keys():
    """Check if API keys are configured"""
    anthropic_configured = "ANTHROPIC_API_KEY" in os.environ and bool(os.environ.get("ANTHROPIC_API_KEY"))
    openai_configured = "OPENAI_API_KEY" in os.environ and bool(os.environ.get("OPENAI_API_KEY"))
    
    return jsonify({
        "anthropic_configured": anthropic_configured,
        "openai_configured": openai_configured
    })


@api_bp.route("/set-api-keys", methods=["POST"])
def set_api_keys():
    """Set API keys in environment variables"""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    anthropic_key = data.get("anthropic_key", "").strip()
    openai_key = data.get("openai_key", "").strip()
    
    # Validate Anthropic key (required)
    if not anthropic_key:
        return jsonify({"error": "Anthropic API key is required"}), 400
    
    # Basic validation - check if keys have the expected prefix
    if not anthropic_key.startswith("sk-ant-"):
        return jsonify({"error": "Invalid Anthropic API key format"}), 400
    
    if openai_key and not openai_key.startswith("sk-"):
        return jsonify({"error": "Invalid OpenAI API key format"}), 400
    
    # Set environment variables
    os.environ["ANTHROPIC_API_KEY"] = anthropic_key
    if openai_key:
        os.environ["OPENAI_API_KEY"] = openai_key
    
    # After setting environment variables, reinitialize LLM for all active sessions
    try:
        from agent.session_manager import sessions
        from agent.llm import LLM
        
        for session_id, session_data in sessions.items():
            if session_data.get("llm") is None:
                # Try to initialize LLM now that API key is available
                try:
                    session_data["llm"] = LLM("claude-3-7-sonnet-latest", session_id)
                    print(f"Successfully initialized LLM for session {session_id}")
                except Exception as e:
                    print(f"Failed to initialize LLM for session {session_id}: {e}")
    except Exception as e:
        print(f"Error reinitializing LLMs: {e}")
    
    return jsonify({
        "success": True,
        "anthropic_configured": True,
        "openai_configured": bool(openai_key)
    })