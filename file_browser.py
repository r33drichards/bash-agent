#!/usr/bin/env python3
"""
File Browser Web Application
A web-based file browser with preview, upload, and download capabilities.
"""

import os
import json
import mimetypes
import base64
import zipfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote
from werkzeug.utils import secure_filename
from werkzeug.exceptions import NotFound, Forbidden

from flask import (
    Flask, render_template, request, jsonify, send_file, 
    abort, redirect, url_for, flash, session
)
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
ROOT_PATH = os.path.abspath('.')  # Start from current directory
ALLOWED_EXTENSIONS = {'txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md', 'yml', 'yaml', 'ini', 'cfg', 'conf'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp'}
ARCHIVE_EXTENSIONS = {'zip', 'tar', 'gz', 'rar', '7z'}

# Security: Prevent access to sensitive files/directories
BLOCKED_PATTERNS = {
    '.*',  # Hidden files starting with .
    '__pycache__',
    '*.pyc',
    'node_modules',
    '.git',
    '.env*',
    'id_rsa*',
    '*.key',
    '*.pem'
}

def is_safe_path(path):
    """Check if path is safe to access"""
    try:
        real_path = os.path.realpath(path)
        root_real = os.path.realpath(ROOT_PATH)
        return real_path.startswith(root_real)
    except:
        return False

def is_blocked_path(path):
    """Check if path matches blocked patterns"""
    path_name = os.path.basename(path)
    return any(pattern.replace('*', '') in path_name for pattern in BLOCKED_PATTERNS)

def get_file_info(path):
    """Get detailed file information"""
    try:
        stat = os.stat(path)
        return {
            'name': os.path.basename(path),
            'path': path,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'is_dir': os.path.isdir(path),
            'is_file': os.path.isfile(path),
            'extension': Path(path).suffix.lower().lstrip('.'),
            'mime_type': mimetypes.guess_type(path)[0] or 'application/octet-stream'
        }
    except (OSError, IOError):
        return None

def format_file_size(size):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def get_file_icon(file_info):
    """Get appropriate icon for file type"""
    if file_info['is_dir']:
        return '📁'
    
    ext = file_info['extension']
    if ext in IMAGE_EXTENSIONS:
        return '🖼️'
    elif ext in ['py']:
        return '🐍'
    elif ext in ['js', 'ts']:
        return '📄'
    elif ext in ['html', 'htm']:
        return '🌐'
    elif ext in ['css', 'scss', 'sass']:
        return '🎨'
    elif ext in ['json', 'yaml', 'yml', 'xml']:
        return '⚙️'
    elif ext in ['txt', 'md', 'rst']:
        return '📝'
    elif ext in ARCHIVE_EXTENSIONS:
        return '📦'
    elif ext in ['pdf']:
        return '📄'
    elif ext in ['mp3', 'wav', 'flac', 'ogg']:
        return '🎵'
    elif ext in ['mp4', 'avi', 'mov', 'mkv']:
        return '🎬'
    else:
        return '📄'

@app.route('/')
def index():
    """Render main file browser interface"""
    return render_template('file_browser.html')

@app.route('/api/files')
def list_files():
    """List files and directories at given path"""
    path = request.args.get('path', ROOT_PATH)
    path = unquote(path)
    
    # Security checks
    if not is_safe_path(path) or is_blocked_path(path):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(path):
        return jsonify({'error': 'Path not found'}), 404
    
    if not os.path.isdir(path):
        return jsonify({'error': 'Path is not a directory'}), 400
    
    try:
        items = []
        for item_name in sorted(os.listdir(path)):
            item_path = os.path.join(path, item_name)
            
            # Skip blocked items
            if is_blocked_path(item_path):
                continue
            
            file_info = get_file_info(item_path)
            if file_info:
                file_info['icon'] = get_file_icon(file_info)
                file_info['size_formatted'] = format_file_size(file_info['size'])
                items.append(file_info)
        
        # Sort: directories first, then files
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        
        return jsonify({
            'success': True,
            'path': path,
            'parent': os.path.dirname(path) if path != ROOT_PATH else None,
            'items': items
        })
    
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download')
def download_file():
    """Download a file"""
    file_path = request.args.get('path')
    if not file_path:
        return jsonify({'error': 'No path specified'}), 400
    
    file_path = unquote(file_path)
    
    # Security checks
    if not is_safe_path(file_path) or is_blocked_path(file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    if os.path.isdir(file_path):
        # Create a zip file for directories
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        try:
            with zipfile.ZipFile(temp_file.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(file_path):
                    # Filter out blocked directories
                    dirs[:] = [d for d in dirs if not is_blocked_path(os.path.join(root, d))]
                    
                    for file in files:
                        full_path = os.path.join(root, file)
                        if not is_blocked_path(full_path):
                            arc_path = os.path.relpath(full_path, file_path)
                            zipf.write(full_path, arc_path)
            
            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=f"{os.path.basename(file_path)}.zip",
                mimetype='application/zip'
            )
        except Exception as e:
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
            return jsonify({'error': str(e)}), 500
    else:
        # Send individual file
        try:
            return send_file(
                file_path,
                as_attachment=True,
                download_name=os.path.basename(file_path)
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/preview')
def preview_file():
    """Preview file content"""
    file_path = request.args.get('path')
    if not file_path:
        return jsonify({'error': 'No path specified'}), 400
    
    file_path = unquote(file_path)
    
    # Security checks
    if not is_safe_path(file_path) or is_blocked_path(file_path):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    file_info = get_file_info(file_path)
    if not file_info:
        return jsonify({'error': 'Cannot read file info'}), 500
    
    try:
        ext = file_info['extension']
        mime_type = file_info['mime_type']
        
        # Text files
        if ext in ALLOWED_EXTENSIONS or mime_type.startswith('text/'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(10000)  # Limit to first 10KB
                return jsonify({
                    'success': True,
                    'type': 'text',
                    'content': content,
                    'truncated': len(content) == 10000,
                    'file_info': file_info
                })
        
        # Images
        elif ext in IMAGE_EXTENSIONS:
            with open(file_path, 'rb') as f:
                content = f.read(1024 * 1024)  # Limit to 1MB
                base64_content = base64.b64encode(content).decode('utf-8')
                return jsonify({
                    'success': True,
                    'type': 'image',
                    'content': f"data:{mime_type};base64,{base64_content}",
                    'file_info': file_info
                })
        
        # Binary files - just show file info
        else:
            return jsonify({
                'success': True,
                'type': 'binary',
                'message': 'Binary file - preview not available',
                'file_info': file_info
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_files():
    """Upload files to specified directory"""
    target_path = request.form.get('path', ROOT_PATH)
    target_path = unquote(target_path)
    
    # Security checks
    if not is_safe_path(target_path):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        return jsonify({'error': 'Invalid target directory'}), 400
    
    if 'files' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
    
    files = request.files.getlist('files')
    uploaded_files = []
    errors = []
    
    for file in files:
        if file.filename == '':
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
                file_info['icon'] = get_file_icon(file_info)
                file_info['size_formatted'] = format_file_size(file_info['size'])
                uploaded_files.append(file_info)
        
        except Exception as e:
            errors.append(f"Failed to upload {file.filename}: {str(e)}")
    
    return jsonify({
        'success': len(uploaded_files) > 0,
        'uploaded_files': uploaded_files,
        'errors': errors
    })

@app.route('/api/create_folder', methods=['POST'])
def create_folder():
    """Create a new folder"""
    data = request.get_json()
    parent_path = data.get('parent_path', ROOT_PATH)
    folder_name = data.get('folder_name', '').strip()
    
    if not folder_name:
        return jsonify({'error': 'Folder name required'}), 400
    
    parent_path = unquote(parent_path)
    
    # Security checks
    if not is_safe_path(parent_path):
        return jsonify({'error': 'Access denied'}), 403
    
    folder_name = secure_filename(folder_name)
    folder_path = os.path.join(parent_path, folder_name)
    
    if os.path.exists(folder_path):
        return jsonify({'error': 'Folder already exists'}), 409
    
    try:
        os.makedirs(folder_path)
        file_info = get_file_info(folder_path)
        if file_info:
            file_info['icon'] = get_file_icon(file_info)
            file_info['size_formatted'] = format_file_size(file_info['size'])
        
        return jsonify({
            'success': True,
            'folder': file_info
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete', methods=['DELETE'])
def delete_item():
    """Delete a file or directory"""
    item_path = request.args.get('path')
    if not item_path:
        return jsonify({'error': 'No path specified'}), 400
    
    item_path = unquote(item_path)
    
    # Security checks
    if not is_safe_path(item_path) or is_blocked_path(item_path):
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(item_path):
        return jsonify({'error': 'Item not found'}), 404
    
    # Don't allow deletion of root path
    if os.path.abspath(item_path) == os.path.abspath(ROOT_PATH):
        return jsonify({'error': 'Cannot delete root directory'}), 403
    
    try:
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print(f"Starting File Browser server...")
    print(f"Root directory: {ROOT_PATH}")
    print(f"Access at: http://localhost:5001")
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
