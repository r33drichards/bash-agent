import os
import mimetypes
from datetime import datetime
from pathlib import Path
from flask import current_app

# File Browser Configuration
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
    if not current_app.config.get("FILE_BROWSER_ROOT"):
        return True

    try:
        abs_path = os.path.abspath(path)
        root_path = os.path.abspath(current_app.config["FILE_BROWSER_ROOT"])
        return abs_path.startswith(root_path)
    except:
        return False


def is_blocked_path(path):
    """Check if path should be blocked from access"""
    blocked_dirs = {".git", "__pycache__", "node_modules", ".svn", ".hg", "venv", "env"}
    path_parts = Path(path).parts
    return any(part in blocked_dirs for part in path_parts)


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
            import base64
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