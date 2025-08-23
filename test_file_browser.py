#!/usr/bin/env python3
import os
import json
import mimetypes
import base64
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

# Configuration
ROOT_PATH = os.getcwd()
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp'}
TEXT_EXTENSIONS = {'txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md', 'yml', 'yaml', 'ini', 'cfg', 'conf', 'sh', 'bat', 'ps1'}

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
    else:
        return '📄'

@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html>
<head><title>File Browser Test</title></head>
<body>
<h1>File Browser Test</h1>
<p>API endpoints:</p>
<ul>
<li><a href="/api/files">/api/files</a> - List files</li>
<li><a href="/api/preview?path=readme.md">/api/preview?path=readme.md</a> - Preview file</li>
</ul>
</body>
</html>'''

@app.route('/api/files')
def list_files():
    """List files and directories at given path"""
    path = request.args.get('path', ROOT_PATH)
    
    if not os.path.exists(path) or not os.path.isdir(path):
        return jsonify({'error': 'Path not found or not a directory'}), 404
    
    try:
        items = []
        for item_name in sorted(os.listdir(path)):
            if item_name.startswith('.'):
                continue  # Skip hidden files for now
            
            item_path = os.path.join(path, item_name)
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
            'items': items
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/preview')
def preview_file():
    """Preview file content"""
    file_path = request.args.get('path')
    if not file_path:
        return jsonify({'error': 'No path specified'}), 400
    
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    file_info = get_file_info(file_path)
    if not file_info:
        return jsonify({'error': 'Cannot read file info'}), 500
    
    try:
        ext = file_info['extension']
        mime_type = file_info['mime_type']
        
        # Text files
        if ext in TEXT_EXTENSIONS or mime_type.startswith('text/'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(5000)  # Limit to first 5KB
                return jsonify({
                    'success': True,
                    'type': 'text',
                    'content': content,
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

if __name__ == '__main__':
    print(f"Starting File Browser Test Server...")
    print(f"Root directory: {ROOT_PATH}")
    print(f"Access at: http://localhost:5002")
    app.run(host='0.0.0.0', port=5002, debug=True)
