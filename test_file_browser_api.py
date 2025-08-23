#!/usr/bin/env python3
"""
Simple test server to verify file browser API works
"""

import os
import json
from pathlib import Path
import mimetypes
from datetime import datetime
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

ROOT_PATH = os.getcwd()
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp'}
TEXT_EXTENSIONS = {'txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md', 'yml', 'yaml'}

def get_file_info(path):
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
    except:
        return None

def format_file_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f'{size:.1f} {unit}'
        size /= 1024.0
    return f'{size:.1f} TB'

def get_file_icon(file_info):
    if file_info['is_dir']:
        return '📁'
    ext = file_info['extension']
    if ext == 'py':
        return '🐍'
    elif ext in ['html', 'htm']:
        return '🌐'
    elif ext in ['md', 'txt']:
        return '📝'
    elif ext in ['json', 'yaml', 'yml']:
        return '⚙️'
    return '📄'

@app.route('/')
def index():
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>File Browser API Test</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #e6edf3; padding: 20px; }
        .btn { background: #21262d; color: #e6edf3; border: 1px solid #30363d; padding: 8px 16px; margin: 5px; cursor: pointer; }
        .result { background: #161b22; border: 1px solid #21262d; padding: 15px; margin: 10px 0; border-radius: 6px; }
    </style>
</head>
<body>
    <h1>🧪 File Browser API Test</h1>
    <button class="btn" onclick="testAPI()">Test /api/files</button>
    <div id="result" class="result">Click "Test /api/files" to test the API</div>
    
    <script>
        async function testAPI() {
            const result = document.getElementById('result');
            result.innerHTML = 'Testing API...';
            
            try {
                const response = await fetch('/api/files');
                const data = await response.json();
                
                result.innerHTML = `
                    <strong>Status:</strong> ${response.status}<br>
                    <strong>Success:</strong> ${data.success}<br>
                    <strong>Path:</strong> ${data.path}<br>
                    <strong>Items:</strong> ${data.items ? data.items.length : 0}<br><br>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;
            } catch (error) {
                result.innerHTML = `<strong>Error:</strong> ${error.message}`;
            }
        }
    </script>
</body>
</html>
    ''')

@app.route('/api/files')
def list_files():
    try:
        items = []
        for item_name in sorted(os.listdir(ROOT_PATH)):
            if item_name.startswith('.'):
                continue
                
            item_path = os.path.join(ROOT_PATH, item_name)
            file_info = get_file_info(item_path)
            if file_info:
                file_info['icon'] = get_file_icon(file_info)
                file_info['size_formatted'] = format_file_size(file_info['size'])
                items.append(file_info)
        
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        
        return jsonify({
            'success': True,
            'path': ROOT_PATH,
            'parent': None,
            'items': items
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print(f'Starting File Browser API Test Server...')
    print(f'Root directory: {ROOT_PATH}')
    print(f'Test at: http://localhost:5001')
    app.run(host='0.0.0.0', port=5001, debug=True)
