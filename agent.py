import os
import subprocess
import argparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import uuid
import threading
from datetime import datetime
import time
import tempfile
import psutil
import base64

import anthropic
from anthropic import RateLimitError, APIError
import sqlite3
import json
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output
import io
import contextlib

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

# Store uploaded files temporarily by file ID
uploaded_files = {}

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(script_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global sessions store
sessions = {}

def save_conversation_history(session_id):
    """Save conversation history to JSON file in metadata directory"""
    if not app.config.get('METADATA_DIR'):
        return
    
    if session_id not in sessions:
        return
    
    history = sessions[session_id]['conversation_history']
    if not history:
        return
    
    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_{session_id[:8]}_{timestamp}.json"
    filepath = os.path.join(app.config['METADATA_DIR'], filename)
    
    # Save conversation data
    conversation_data = {
        'session_id': session_id,
        'started_at': sessions[session_id]['connected_at'].isoformat(),
        'ended_at': datetime.now().isoformat(),
        'history': history
    }
    
    try:
        with open(filepath, 'w') as f:
            json.dump(conversation_data, f, indent=2)
        print(f"Conversation history saved to: {filepath}")
    except Exception as e:
        print(f"Error saving conversation history: {e}")

def load_conversation_history():
    """Load all conversation history files from metadata directory"""
    if not app.config.get('METADATA_DIR'):
        return []
    
    if not os.path.exists(app.config['METADATA_DIR']):
        return []
    
    conversations = []
    try:
        for filename in os.listdir(app.config['METADATA_DIR']):
            if filename.startswith('conversation_') and filename.endswith('.json'):
                filepath = os.path.join(app.config['METADATA_DIR'], filename)
                with open(filepath, 'r') as f:
                    conversation_data = json.load(f)
                    conversations.append(conversation_data)
        
        # Sort by started_at timestamp
        conversations.sort(key=lambda x: x['started_at'], reverse=True)
        
    except Exception as e:
        print(f"Error loading conversation history: {e}")
    
    return conversations

# File Browser Configuration
ROOT_PATH = os.getcwd()  # Use current working directory
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp'}
TEXT_EXTENSIONS = {'txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md', 'yml', 'yaml', 'ini', 'cfg', 'conf', 'sh', 'bat', 'ps1'}
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

def main():
    parser = argparse.ArgumentParser(description='LLM Agent Web Server')

    parser.add_argument('--port', type=int, default=5000, help='Port to run the server on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to run the server on')
    parser.add_argument('--auto-confirm', action='store_true', help='Automatically confirm all actions without prompting')
    parser.add_argument('--working-dir', type=str, default=None, help='Set the working directory for tool execution')
    parser.add_argument('--metadata-dir', type=str, default=None, help='Directory to store conversation history and metadata')
    # system prompt
    parser.add_argument('--system-prompt', type=str, default=None, help='System prompt to use for the agent')
    args = parser.parse_args()
    
    # Store global config
    app.config['AUTO_CONFIRM'] = args.auto_confirm
    app.config['WORKING_DIR'] = args.working_dir
    app.config['METADATA_DIR'] = args.metadata_dir
    app.config['SYSTEM_PROMPT'] = args.system_prompt
    
    # Change working directory if specified
    if args.working_dir:
        if os.path.exists(args.working_dir):
            os.chdir(args.working_dir)
            print(f"Working directory changed to: {args.working_dir}")
        else:
            print(f"Warning: Working directory {args.working_dir} does not exist")
            return
    
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
    print("Claude Code-like interface available in your browser")
    
    socketio.run(app, host=args.host, port=args.port, debug=True, allow_unsafe_werkzeug=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/conversation-history')
def get_conversation_history():
    """API endpoint to get conversation history"""
    history = load_conversation_history()
    return jsonify(history)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """API endpoint to handle file uploads and return content"""
    print("=== UPLOAD ENDPOINT CALLED ===")
    print(f"Request files: {list(request.files.keys())}")
    
    if 'files' not in request.files and 'file' not in request.files:
        print("ERROR: No files found in request")
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    # Handle both single and multiple file uploads
    files = request.files.getlist('files') if 'files' in request.files else [request.files['file']]
    print(f"Processing {len(files)} files")
    results = []
    
    for i, file in enumerate(files):
        print(f"Processing file {i+1}: {file.filename}")
        if file.filename == '':
            print("  Skipping empty filename")
            continue
            
        try:
            # Create temp file to store upload
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as temp_file:
                file.save(temp_file.name)
                temp_path = temp_file.name
            
            # Check if it's an image
            file_ext = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
            is_image = file_ext in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']
            print(f"  File extension: {file_ext}, is_image: {is_image}")
            
            # Read file content
            try:
                # Try to read as text first
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    file_type = 'text'
                    # For small text files, include content directly
                    if len(content) < 10000:  # 10KB limit for direct content
                        os.unlink(temp_path)
                        print(f"  Read small text content: {len(content)} chars")
                        results.append({
                            'name': file.filename,
                            'content': content,
                            'type': file_type,
                            'size': len(content)
                        })
                        continue
            except UnicodeDecodeError:
                # Binary file
                if is_image:
                    file_type = 'image'
                else:
                    file_type = 'binary'
            
            # For large files or binary files, store them temporarily and return a file ID
            file_id = str(uuid.uuid4())
            
            # Store file info
            uploaded_files[file_id] = {
                'path': temp_path,
                'filename': file.filename,
                'type': file_type,
                'uploaded_at': datetime.now()
            }
            
            # Get file size
            file_size = os.path.getsize(temp_path)
            print(f"  Stored large/binary file with ID: {file_id}, size: {file_size} bytes")
            
            results.append({
                'name': file.filename,
                'file_id': file_id,
                'type': file_type,
                'size': file_size
            })
                
        except Exception as e:
            print(f"  Error processing file: {e}")
            results.append({
                'name': file.filename,
                'error': str(e)
            })
    
    if not results:
        return jsonify({'success': False, 'error': 'No valid files uploaded'}), 400
        
    return jsonify({
        'success': True,
        'files': results
    })


def get_file_content_by_id(file_id: str) -> dict:
    """Get file content by file ID."""
    if file_id not in uploaded_files:
        return {'error': 'File not found'}
    
    file_info = uploaded_files[file_id]
    
    try:
        if file_info['type'] == 'text':
            with open(file_info['path'], 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            # For binary/image files, read as base64
            with open(file_info['path'], 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
        
        return {
            'name': file_info['filename'],
            'content': content,
            'type': file_info['type'],
            'size': len(content)
        }
    
    except Exception as e:
        return {'error': str(e)}


@app.route('/api/files')
def list_files():
    """List files and directories at given path"""
    path = request.args.get('path', ROOT_PATH)
    path = unquote(path) if path else ROOT_PATH
    
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
        if ext in TEXT_EXTENSIONS or mime_type.startswith('text/'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(50000)  # Limit to first 50KB
                return jsonify({
                    'success': True,
                    'type': 'text',
                    'content': content,
                    'truncated': len(content) == 50000,
                    'file_info': file_info
                })
        
        # Images
        elif ext in IMAGE_EXTENSIONS:
            with open(file_path, 'rb') as f:
                content = f.read(2 * 1024 * 1024)  # Limit to 2MB
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

@app.route('/api/upload-to-path', methods=['POST'])
def upload_to_path():
    """Upload files to a specific directory"""
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
    uploaded_files_result = []
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
                uploaded_files_result.append(file_info)
        
        except Exception as e:
            errors.append(f"Failed to upload {file.filename}: {str(e)}")
    
    return jsonify({
        'success': len(uploaded_files_result) > 0,
        'uploaded_files': uploaded_files_result,
        'errors': errors
    })

def cleanup_old_files():
    """Clean up files older than 1 hour."""
    current_time = datetime.now()
    files_to_remove = []
    
    for file_id, file_info in uploaded_files.items():
        if (current_time - file_info['uploaded_at']).seconds > 3600:  # 1 hour
            files_to_remove.append(file_id)
    
    for file_id in files_to_remove:
        file_info = uploaded_files[file_id]
        try:
            if os.path.exists(file_info['path']):
                os.unlink(file_info['path'])
        except Exception:
            pass
        del uploaded_files[file_id]

@socketio.on('connect')
def handle_connect(auth=None):
    session_id = str(uuid.uuid4())
    join_room(session_id)
    session['session_id'] = session_id
    
    # Initialize session with LLM
    sessions[session_id] = {
        'llm': LLM("claude-3-7-sonnet-latest", session_id),
        'auto_confirm': app.config['AUTO_CONFIRM'],
        'connected_at': datetime.now(),
        'conversation_history': [],
        'memory_manager': MemoryManager(),
        'todo_manager': TodoManager()
    }
    
    emit('session_started', {'session_id': session_id})
    emit('message', {
        'type': 'system',
        'content': 'Connected to Claude Code Agent. Type your message to start...',
        'timestamp': datetime.now().isoformat()
    })
    
    # Send conversation history if available
    history = load_conversation_history()
    if history:
        emit('conversation_history', history)

@socketio.on('disconnect')
def handle_disconnect():
    session_id = session.get('session_id')
    if session_id in sessions:
        # Save conversation history before cleanup
        save_conversation_history(session_id)
        del sessions[session_id]
    leave_room(session_id)

@socketio.on('user_message')
def handle_user_message(data):
    print(f"=== USER_MESSAGE EVENT RECEIVED ===")
    print(f"Raw data received: {data}")
    
    session_id = session.get('session_id')
    print(f"Session ID: {session_id}")
    
    if session_id not in sessions:
        print(f"ERROR: Session {session_id} not found in sessions")
        emit('error', {'message': 'Session not found'})
        return
    
    user_input = data.get('message', '').strip()
    print(f"User input: '{user_input}'")
    
    if not user_input:
        print("ERROR: No user input provided")
        return
    
    # Clean up old uploaded files periodically
    cleanup_old_files()
    
    # Get attached files and resolve content for LLM processing
    attached_files = data.get('files', [])
    print(f"Attached files received: {len(attached_files)} files")
    
    # Process files - resolve file_id references to actual content
    resolved_files = []
    for i, file_info in enumerate(attached_files):
        print(f"  File {i+1}: {file_info.get('name', 'unknown')} - type: {file_info.get('type', 'unknown')}")
        
        if 'content' in file_info:
            # Small file with direct content
            resolved_files.append(file_info)
            print(f"    Direct content: {len(str(file_info.get('content', '')))} chars")
        elif 'file_id' in file_info:
            # Large file stored with file_id - retrieve content
            file_data = get_file_content_by_id(file_info['file_id'])
            if 'error' in file_data:
                print(f"    Error loading file: {file_data['error']}")
                # Add error info
                resolved_files.append({
                    'name': file_info['name'],
                    'content': f"[Error loading file: {file_data['error']}]",
                    'type': 'error'
                })
            else:
                print(f"    Retrieved content: {len(str(file_data.get('content', '')))} chars")
                resolved_files.append({
                    'name': file_data['name'],
                    'content': file_data['content'],
                    'type': file_data['type']
                })
    
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
            emit('error', {'message': 'Session expired during file processing'})
            return
        llm = sessions[session_id]['llm']
        
        for file_info in resolved_files:
            if file_info.get('type') == 'image':
                print(f"  Summarizing image: {file_info['name']}")
                # Generate image summary once
                image_summary = llm.summarize_image(file_info['content'], file_info['name'])
                
                # Add to LLM message (for processing)
                llm_message += f"\n\n[Image Description for {file_info['name']}]:\n{image_summary}"
                
                # Add to display message (clean reference)
                display_message += f"\n\n[Image: {file_info['name']}]"
                
                # Add to history message (with description)
                history_message += f"\n\n[Image: {file_info['name']}]\nDescription: {image_summary}"
            else:
                print(f"  Adding file: {file_info['name']}")
                file_content = f"\n\n--- File: {file_info['name']} ---\n{file_info['content']}\n--- End of {file_info['name']} ---"
                
                # Add to all messages (same content for text files)
                llm_message += file_content
                display_message += file_content
                history_message += file_content
    
    # Echo user message (clean version for display)
    user_message_display = {
        'type': 'user',
        'content': display_message,
        'timestamp': datetime.now().isoformat()
    }
    print(f"Emitting user message: {user_message_display}")
    emit('message', user_message_display)
    
    # Store in conversation history (with descriptions)
    user_message_history = {
        'type': 'user',
        'content': history_message,
        'timestamp': datetime.now().isoformat()
    }
    
    # Double-check session still exists before accessing
    if session_id not in sessions:
        print(f"ERROR: Session {session_id} was removed before storing conversation history")
        emit('error', {'message': 'Session expired'})
        return
        
    sessions[session_id]['conversation_history'].append(user_message_history)
    print(f"Added message to conversation history")
    
    # Process with LLM
    print(f"Starting LLM processing...")
    try:
        # Double-check session still exists before accessing LLM components
        if session_id not in sessions:
            print(f"ERROR: Session {session_id} was removed before LLM processing")
            emit('error', {'message': 'Session expired during processing'})
            return
            
        session_data = sessions[session_id]  # Get session data once to avoid multiple lookups
        llm = session_data['llm']
        auto_confirm = session_data['auto_confirm']
        memory_manager = session_data['memory_manager']
        print(f"Retrieved session components: llm={llm is not None}, auto_confirm={auto_confirm}")
        
        # Load relevant memories as context
        relevant_memories = memory_manager.get_memory_context(user_input, max_memories=3)
        
        # Load active todos as context
        todo_manager = session_data['todo_manager']
        active_todos_summary = todo_manager.get_active_todos_summary()
        
        # Load GitHub RAG repositories context
        github_rag_context = ""
        try:
            if 'github_rag' in session_data:
                github_rag = session_data['github_rag']
                github_rag_context = github_rag.get_repository_memory_context()
        except Exception:
            pass
        
        # Prepare message with context
        context_parts = []
        
        if relevant_memories != "No relevant memories found.":
            context_parts.append(relevant_memories)
        
        if active_todos_summary != "No active todos.":
            context_parts.append(active_todos_summary)
            
        if github_rag_context and github_rag_context != "No GitHub repositories have been indexed for RAG queries.":
            context_parts.append(github_rag_context)
        
        if context_parts:
            context_msg = "\n\n".join(context_parts) + f"\n\n=== USER MESSAGE ===\n{llm_message}"
            msg = [{"type": "text", "text": context_msg}]
        else:
            msg = [{"type": "text", "text": llm_message}]
        
        print(f"Final message to LLM: {msg[0]['text'][:200]}..." if len(msg[0]['text']) > 200 else f"Final message to LLM: {msg[0]['text']}")
        print("Calling LLM with streaming...")
        
        # Define streaming callback
        def stream_callback(chunk, stream_type):
            emit('message_chunk', {
                'type': 'agent',
                'chunk': chunk,
                'stream_type': stream_type,
                'timestamp': datetime.now().isoformat()
            })
        
        # Call LLM with streaming
        output, tool_calls = llm(msg, stream_callback=stream_callback)
        print(f"LLM response received: {len(output)} chars, {len(tool_calls) if tool_calls else 0} tool calls")
        
        # Send final agent response (for history)
        agent_message = {
            'type': 'agent',
            'content': output,
            'timestamp': datetime.now().isoformat()
        }
        emit('message_complete', agent_message)
        
        # Store in conversation history - check session still exists
        if session_id in sessions:
            sessions[session_id]['conversation_history'].append(agent_message)
        else:
            print(f"ERROR: Session {session_id} was removed before storing agent response")
        
        # Handle tool calls
        if tool_calls:
            for tool_call in tool_calls:
                handle_tool_call_web(tool_call, session_id, auto_confirm)
                
    except Exception as e:
        emit('message', {
            'type': 'error',
            'content': f'Error: {str(e)}',
            'timestamp': datetime.now().isoformat()
        })

@socketio.on('tool_confirm')
def handle_tool_confirm(data):
    session_id = session.get('session_id')
    if session_id not in sessions:
        emit('error', {'message': 'Session not found'})
        return
    
    confirmed = data.get('confirmed', False)
    
    if confirmed:
        # Execute the tool call
        tool_call = data.get('tool_call')
        if tool_call:
            execute_tool_call_web(tool_call, session_id)
    else:
        # Handle tool cancellation with proper tool_result
        tool_call = data.get('tool_call')
        rejection_reason = data.get('rejection_reason', '')
        
        if tool_call:
            # Create a tool_result for the cancelled tool
            cancellation_message = 'Tool execution cancelled by user.'
            if rejection_reason:
                cancellation_message += f' Reason: {rejection_reason}'
            
            tool_result = {
                'type': 'tool_result',
                'tool_use_id': tool_call['id'],
                'content': [{'type': 'text', 'text': f'Error: {cancellation_message}'}]
            }
            
            # Send cancellation message to user
            emit('message', {
                'type': 'system',
                'content': cancellation_message,
                'timestamp': datetime.now().isoformat()
            })
            
            # Send tool_result back to LLM to continue conversation
            llm = sessions[session_id]['llm']
            output, new_tool_calls = llm([tool_result])
            
            # Send agent response
            agent_message = {
                'type': 'agent',
                'content': output,
                'timestamp': datetime.now().isoformat()
            }
            emit('message', agent_message, room=session_id)
            
            # Store in conversation history
            sessions[session_id]['conversation_history'].append(agent_message)
            
            # Handle any new tool calls
            if new_tool_calls:
                for new_tool_call in new_tool_calls:
                    handle_tool_call_web(new_tool_call, session_id, sessions[session_id]['auto_confirm'])
        else:
            # Fallback if no tool_call data
            emit('message', {
                'type': 'system', 
                'content': 'Tool execution cancelled by user.',
                'timestamp': datetime.now().isoformat()
            })

@socketio.on('update_auto_confirm')
def handle_update_auto_confirm(data):
    session_id = session.get('session_id')
    if session_id not in sessions:
        emit('error', {'message': 'Session not found'})
        return
    
    enabled = data.get('enabled', False)
    sessions[session_id]['auto_confirm'] = enabled
    
    # Send confirmation message
    status = 'enabled' if enabled else 'disabled'
    emit('message', {
        'type': 'system',
        'content': f'Auto-confirm {status}.',
        'timestamp': datetime.now().isoformat()
    })

@socketio.on('get_auto_confirm_state')
def handle_get_auto_confirm_state():
    session_id = session.get('session_id')
    if session_id not in sessions:
        emit('error', {'message': 'Session not found'})
        return
    
    enabled = sessions[session_id]['auto_confirm']
    emit('auto_confirm_state', {'enabled': enabled})

def handle_tool_call_web(tool_call, session_id, auto_confirm):
    """Handle tool call in web context"""
    if auto_confirm:
        execute_tool_call_web(tool_call, session_id)
    else:
        # Send confirmation request
        emit('tool_confirmation', {
            'tool_call_id': tool_call['id'],
            'tool_name': tool_call['name'],
            'tool_input': tool_call['input'],
            'tool_call': tool_call
        }, room=session_id)

def execute_tool_call_web(tool_call, session_id):
    """Execute tool call and emit results"""
    try:
        # Send detailed tool execution info
        tool_info = {
            'type': 'tool_execution',
            'tool_name': tool_call['name'],
            'tool_input': tool_call['input'],
            'timestamp': datetime.now().isoformat()
        }
        
        # Add the actual code/command being executed
        if tool_call['name'] == 'bash':
            tool_info['code'] = tool_call['input']['command']
            tool_info['language'] = 'bash'
            tool_info['timeout'] = tool_call['input'].get('timeout', 30)
            tool_info['stream_output'] = tool_call['input'].get('stream_output', False)
        elif tool_call['name'] == 'ipython':
            tool_info['code'] = tool_call['input']['code']
            tool_info['language'] = 'python'
        elif tool_call['name'] == 'sqlite':
            tool_info['code'] = tool_call['input']['query']
            tool_info['language'] = 'sql'
        
        emit('tool_execution_start', tool_info, room=session_id)
        
        # Execute the tool
        result = execute_tool_call(tool_call)
        
        # Extract the result content
        result_content = ""
        plots = []
        if result and 'content' in result and result['content']:
            result_content = result['content'][0]['text'] if result['content'][0]['type'] == 'text' else str(result['content'])
        
        # Extract plots if available (from IPython execution)
        if result and 'plots' in result:
            plots = result['plots']
        
        # Send detailed execution result
        result_data = {
            'type': 'tool_result',
            'tool_name': tool_call['name'],
            'result': result_content,
            'timestamp': datetime.now().isoformat()
        }
        
        if plots:
            result_data['plots'] = plots
            
        emit('tool_execution_result', result_data, room=session_id)
        
        # Send result back to LLM
        llm = sessions[session_id]['llm']
        output, new_tool_calls = llm([result])
        
        # Send agent response
        agent_message = {
            'type': 'agent',
            'content': output,
            'timestamp': datetime.now().isoformat()
        }
        emit('message', agent_message, room=session_id)
        
        # Store in conversation history
        sessions[session_id]['conversation_history'].append(agent_message)
        
        # Handle any new tool calls
        if new_tool_calls:
            for new_tool_call in new_tool_calls:
                handle_tool_call_web(new_tool_call, session_id, sessions[session_id]['auto_confirm'])
                
    except Exception as e:
        emit('message', {
            'type': 'error',
            'content': f'Tool execution error: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }, room=session_id)

def execute_tool_call(tool_call):
    """Execute a tool call and return the result"""
    if tool_call["name"] == "bash":
        command = tool_call["input"]["command"]
        timeout = tool_call["input"].get("timeout", 30)
        stream_output = tool_call["input"].get("stream_output", False)
        output_text = execute_bash(command, timeout, stream_output)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
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
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "ipython":
        code = tool_call["input"]["code"]
        print_result = tool_call["input"].get("print_result", False)
        output_text, plots = execute_ipython(code, print_result)
        result = dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
        return result
    elif tool_call["name"] == "edit_file_diff":
        file_path = tool_call["input"]["file_path"]
        diff = tool_call["input"]["diff"]
        output_text = apply_unified_diff(file_path, diff)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "overwrite_file":
        file_path = tool_call["input"]["file_path"]
        content = tool_call["input"]["content"]
        output_text = overwrite_file(file_path, content)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "read_file":
        file_path = tool_call["input"]["file_path"]
        output_text = read_file(file_path)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "search_files":
        pattern = tool_call["input"]["pattern"]
        path = tool_call["input"]["path"]
        file_extensions = tool_call["input"].get("file_extensions")
        ignore_dirs = tool_call["input"].get("ignore_dirs")
        case_sensitive = tool_call["input"].get("case_sensitive", False)
        regex = tool_call["input"].get("regex", False)
        max_results = tool_call["input"].get("max_results", 100)
        output_text = search_files(pattern, path, file_extensions, ignore_dirs, case_sensitive, regex, max_results)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "save_memory":
        title = tool_call["input"]["title"]
        content = tool_call["input"]["content"]
        tags = tool_call["input"].get("tags", [])
        output_text = save_memory(title, content, tags)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "search_memory":
        query = tool_call["input"].get("query")
        tags = tool_call["input"].get("tags")
        limit = tool_call["input"].get("limit", 10)
        output_text = search_memory(query, tags, limit)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "list_memories":
        limit = tool_call["input"].get("limit", 20)
        offset = tool_call["input"].get("offset", 0)
        output_text = list_memories(limit, offset)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "get_memory":
        memory_id = tool_call["input"]["memory_id"]
        output_text = get_memory(memory_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "delete_memory":
        memory_id = tool_call["input"]["memory_id"]
        output_text = delete_memory(memory_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "create_todo":
        title = tool_call["input"]["title"]
        description = tool_call["input"].get("description", "")
        priority = tool_call["input"].get("priority", "medium")
        project = tool_call["input"].get("project")
        due_date = tool_call["input"].get("due_date")
        tags = tool_call["input"].get("tags")
        estimated_hours = tool_call["input"].get("estimated_hours")
        output_text = create_todo(title, description, priority, project, due_date, tags, estimated_hours)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "update_todo":
        todo_id = tool_call["input"]["todo_id"]
        updates = {k: v for k, v in tool_call["input"].items() if k != "todo_id"}
        output_text = update_todo(todo_id, **updates)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
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
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "get_kanban_board":
        project = tool_call["input"].get("project")
        output_text = get_kanban_board(project)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "search_todos":
        query = tool_call["input"]["query"]
        include_completed = tool_call["input"].get("include_completed", False)
        output_text = search_todos(query, include_completed)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "get_todo":
        todo_id = tool_call["input"]["todo_id"]
        output_text = get_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "delete_todo":
        todo_id = tool_call["input"]["todo_id"]
        output_text = delete_todo(todo_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "get_todo_stats":
        project = tool_call["input"].get("project")
        output_text = get_todo_stats(project)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "github_rag_index":
        repo_url = tool_call["input"]["repo_url"]
        include_extensions = tool_call["input"].get("include_extensions")
        ignore_dirs = tool_call["input"].get("ignore_dirs")
        output_text = github_rag_index(repo_url, include_extensions, ignore_dirs)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "github_rag_query":
        collection_name = tool_call["input"]["collection_name"]
        question = tool_call["input"]["question"]
        max_results = tool_call["input"].get("max_results", 5)
        output_text = github_rag_query(collection_name, question, max_results)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "github_rag_list":
        output_text = github_rag_list()
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    else:
        raise Exception(f"Unsupported tool: {tool_call['name']}")


bash_tool = {
    "name": "bash",
    "description": "Execute bash commands and return the output. Supports custom timeouts and real-time streaming for long-running commands.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30, max: 3600 for 1 hour)"
            },
            "stream_output": {
                "type": "boolean",
                "description": "Stream output in real-time for long-running commands (default: false)"
            }
        },
        "required": ["command"]
    }
}

sqlite_tool = {
    "name": "sqlite",
    "description": "Execute SQL queries on a specified SQLite database file and return the results. For large SELECT queries, you can specify an optional output_json file path to write the full results as JSON. You can also set 'print_result' to true to print the results in the context window, even if output_json is specified. This is useful for letting the agent see and reason about the data in context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "Path to the SQLite database file."
            },
            "query": {
                "type": "string",
                "description": "The SQL query to execute."
            },
            "output_json": {
                "type": "string",
                "description": "Optional path to a JSON file to write the full query result to (for SELECT queries)."
            },
            "print_result": {
                "type": "boolean",
                "description": "If true, print the query result in the context window, even if output_json is specified."
            }
        },
        "required": ["db_path", "query"]
    }
}

# --- IPython tool definition ---
ipython_tool = {
    "name": "ipython",
    "description": "Execute Python code using IPython and return the output, including rich output (text, images, etc.). Optionally print the result in the context window.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute."
            },
            "print_result": {
                "type": "boolean",
                "description": "If true, print the result in the context window."
            }
        },
        "required": ["code"]
    }
}

# --- Edit File tool definitions ---
edit_file_diff_tool = {
    "name": "edit_file_diff",
    "description": """Apply a unified diff patch to a file with robust error handling and validation.

SUPPORTED FORMATS:
- Standard unified diff format (git diff output)
- Traditional diff -u format  
- Both git-style (a/, b/ prefixes) and traditional formats

KEY FEATURES:
- Built-in parser with detailed error messages
- Fallback to external python-patch library if available
- Validates patch format before applying
- Handles new file creation and existing file modification
- Fuzzy matching for minor whitespace differences
- Comprehensive error reporting with line numbers

USAGE GUIDELINES:
- Use for precise line-by-line edits with context
- Ideal when you have exact diff output from git or diff tools
- Ensure patch context matches the current file state
- For large changes, consider using overwrite_file instead
- Always include sufficient context lines (3+ recommended)

EXAMPLE DIFF FORMAT:
```
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def example():
+    print("new line")
     return True
```""",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit. File will be created if it doesn't exist."
            },
            "diff": {
                "type": "string",
                "description": "Unified diff string in standard format. Must include @@ hunk headers and proper line prefixes (space, +, -)."
            }
        },
        "required": ["file_path", "diff"]
    }
}

overwrite_file_tool = {
    "name": "overwrite_file",
    "description": "Overwrite a file with new content. The input should include the file path and the new content as a string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to overwrite."
            },
            "content": {
                "type": "string",
                "description": "The new content to write to the file."
            }
        },
        "required": ["file_path", "content"]
    }
}

read_file_tool = {
    "name": "read_file",
    "description": "Read the contents of a file with line numbers for easy reference by LLM. Useful for viewing and analyzing code or text files.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read."
            }
        },
        "required": ["file_path"]
    }
}

search_files_tool = {
    "name": "search_files",
    "description": "Search for text patterns across files with line numbers for easy reference. Can search individual files or recursively across directories. Supports regex patterns and various file filters.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Text pattern or regex to search for"
            },
            "path": {
                "type": "string",
                "description": "File path or directory to search in. If a directory, searches recursively."
            },
            "file_extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of file extensions to include (e.g., ['py', 'js', 'txt']). If not specified, searches all text files."
            },
            "ignore_dirs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of directories to ignore (e.g., ['node_modules', '.git', '__pycache__'])"
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether search should be case sensitive (default: false)"
            },
            "regex": {
                "type": "boolean",
                "description": "Whether pattern should be treated as regex (default: false)"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matches to return (default: 100)"
            }
        },
        "required": ["pattern", "path"]
    }
}


# Memory tool definitions
save_memory_tool = {
    "name": "save_memory",
    "description": "Save information to memory for future reference. Use this to store important facts, solutions, or insights that might be useful later.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "A descriptive title for the memory"
            },
            "content": {
                "type": "string", 
                "description": "The content to store in memory"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to categorize the memory"
            }
        },
        "required": ["title", "content"]
    }
}

search_memory_tool = {
    "name": "search_memory",
    "description": "Search stored memories by content, title, or tags. Use this to recall previously stored information.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to find relevant memories"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to filter memories"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return (default: 10)"
            }
        }
    }
}

list_memories_tool = {
    "name": "list_memories",
    "description": "List all stored memories with optional pagination.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return (default: 20)"
            },
            "offset": {
                "type": "integer", 
                "description": "Number of memories to skip (default: 0)"
            }
        }
    }
}

get_memory_tool = {
    "name": "get_memory",
    "description": "Retrieve a specific memory by its ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The ID of the memory to retrieve"
            }
        },
        "required": ["memory_id"]
    }
}

delete_memory_tool = {
    "name": "delete_memory",
    "description": "Delete a memory by its ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The ID of the memory to delete"
            }
        },
        "required": ["memory_id"]
    }
}

# Todo tool definitions
create_todo_tool = {
    "name": "create_todo",
    "description": "Create a new todo item for task tracking. Use this to break down complex work into manageable tasks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "A clear, concise title for the todo"
            },
            "description": {
                "type": "string",
                "description": "Detailed description of what needs to be done"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Priority level of the todo (default: medium)"
            },
            "project": {
                "type": "string",
                "description": "Project or category this todo belongs to"
            },
            "due_date": {
                "type": "string",
                "description": "Due date in YYYY-MM-DD format"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to categorize the todo"
            },
            "estimated_hours": {
                "type": "number",
                "description": "Estimated time to complete in hours"
            }
        },
        "required": ["title"]
    }
}

update_todo_tool = {
    "name": "update_todo",
    "description": "Update an existing todo item. Use this to change state (todo/in_progress/completed), priority, or other details.",
    "input_schema": {
        "type": "object", 
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "The ID of the todo to update"
            },
            "title": {
                "type": "string",
                "description": "New title for the todo"
            },
            "description": {
                "type": "string",
                "description": "New description for the todo"
            },
            "state": {
                "type": "string",
                "enum": ["todo", "in_progress", "completed"],
                "description": "New state for the todo"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "New priority level"
            },
            "project": {
                "type": "string",
                "description": "New project assignment"
            },
            "due_date": {
                "type": "string",
                "description": "New due date in YYYY-MM-DD format"
            },
            "actual_hours": {
                "type": "number",
                "description": "Actual time spent on this todo in hours"
            }
        },
        "required": ["todo_id"]
    }
}

list_todos_tool = {
    "name": "list_todos",
    "description": "List todos with optional filtering by state, priority, or project. Use this to see current work status.",
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": ["todo", "in_progress", "completed"],
                "description": "Filter by state"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Filter by priority"
            },
            "project": {
                "type": "string",
                "description": "Filter by project"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of todos to return (default: 20)"
            }
        }
    }
}

get_kanban_board_tool = {
    "name": "get_kanban_board",
    "description": "Get a kanban board view of all todos organized by state (todo, in_progress, completed).",
    "input_schema": {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Optional project filter"
            }
        }
    }
}

search_todos_tool = {
    "name": "search_todos",
    "description": "Search todos by title or description text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to find todos"
            },
            "include_completed": {
                "type": "boolean",
                "description": "Whether to include completed todos in search (default: false)"
            }
        },
        "required": ["query"]
    }
}

get_todo_tool = {
    "name": "get_todo",
    "description": "Get detailed information about a specific todo by ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "The ID of the todo to retrieve"
            }
        },
        "required": ["todo_id"]
    }
}

delete_todo_tool = {
    "name": "delete_todo",
    "description": "Delete a todo by ID. Use sparingly - usually better to mark as completed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "The ID of the todo to delete"
            }
        },
        "required": ["todo_id"]
    }
}

get_todo_stats_tool = {
    "name": "get_todo_stats",
    "description": "Get statistics about todos (counts by state, priority, overdue items, etc.).",
    "input_schema": {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Optional project filter for stats"
            }
        }
    }
}

github_rag_index_tool = {
    "name": "github_rag_index",
    "description": "Index a GitHub repository for RAG (Retrieval Augmented Generation) queries. This tool clones the repository, processes its files, and creates a searchable vector database for code analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": "GitHub repository URL to clone and index (e.g., https://github.com/user/repo)"
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
            }
        },
        "required": ["repo_url"]
    }
}

github_rag_query_tool = {
    "name": "github_rag_query",
    "description": "Query an indexed GitHub repository using RAG. Ask questions about the codebase and get answers with citations to specific files and code snippets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "collection_name": {
                "type": "string",
                "description": "The collection name of the indexed repository (returned by github_rag_index or shown in github_rag_list)"
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
}

github_rag_list_tool = {
    "name": "github_rag_list",
    "description": "List all indexed GitHub repositories and their collection names for querying.",
    "input_schema": {
        "type": "object",
        "properties": {}
    }
}


def get_current_session_id():
    """Get the current session ID from Flask session context"""
    from flask import session as flask_session
    return flask_session.get('session_id')


def execute_bash(command, timeout=30, stream_output=False):
    """Execute a bash command and return a formatted string with the results."""
    # Limit timeout to reasonable maximum
    timeout = min(max(timeout, 1), 3600)  # Between 1 second and 1 hour
    
    try:
        if stream_output:
            return execute_bash_streaming(command, timeout)
        else:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout
            )
        # encode output so that text doesn't contain [32m      4[39m [38;5;66;03m# Calculate profit metrics[39;00m
        result.stdout = result.stdout.encode('utf-8').decode('utf-8')
        result.stderr = result.stderr.encode('utf-8').decode('utf-8')
        
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nEXIT CODE: {result.returncode}"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {str(e)}"

def execute_bash_streaming(command, timeout=30):
    """Execute bash command with real-time output streaming."""
    import select
    import os
    import fcntl
    
    try:
        # Start the process
        process = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Make stdout and stderr non-blocking
        def make_non_blocking(fd):
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        make_non_blocking(process.stdout.fileno())
        make_non_blocking(process.stderr.fileno())
        
        stdout_data = []
        stderr_data = []
        start_time = time.time()
        
        # Stream output in real-time
        while True:
            # Check if process has finished
            poll_result = process.poll()
            current_time = time.time()
            
            # Check timeout
            if current_time - start_time > timeout:
                process.kill()
                return f"STREAMING OUTPUT:\n{''.join(stdout_data)}\nSTDERR:\n{''.join(stderr_data)}\nERROR: Command timed out after {timeout} seconds"
            
            # Use select to check for available data
            ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
            
            for stream in ready:
                try:
                    if stream == process.stdout:
                        line = process.stdout.readline()
                        if line:
                            stdout_data.append(line)
                            # Emit real-time output to client
                            emit_streaming_output(line, 'stdout')
                    elif stream == process.stderr:
                        line = process.stderr.readline()
                        if line:
                            stderr_data.append(line)
                            # Emit real-time output to client
                            emit_streaming_output(line, 'stderr')
                except:
                    pass  # Ignore blocking errors
            
            # Process finished
            if poll_result is not None:
                # Read any remaining output
                try:
                    remaining_stdout = process.stdout.read()
                    if remaining_stdout:
                        stdout_data.append(remaining_stdout)
                        emit_streaming_output(remaining_stdout, 'stdout')
                except:
                    pass
                
                try:
                    remaining_stderr = process.stderr.read()
                    if remaining_stderr:
                        stderr_data.append(remaining_stderr)
                        emit_streaming_output(remaining_stderr, 'stderr')
                except:
                    pass
                
                break
        
        return f"STREAMING OUTPUT:\n{''.join(stdout_data)}\nSTDERR:\n{''.join(stderr_data)}\nEXIT CODE: {process.returncode}"
        
    except Exception as e:
        return f"Error executing streaming command: {str(e)}"

def emit_streaming_output(data, stream_type):
    """Emit streaming output to the web client if available."""
    try:
        from flask import session as flask_session
        session_id = flask_session.get('session_id')
        if session_id:
            emit('streaming_output', {
                'data': data,
                'stream_type': stream_type,
                'timestamp': datetime.now().isoformat()
            }, room=session_id)
    except:
        pass  # Ignore if not in web context

def execute_sqlite(db_path, query, output_json=None, print_result=False):
    """Execute an SQL query on a SQLite database and return the results or error. Optionally write SELECT results to a JSON file and/or print them."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        if query.strip().lower().startswith("select"):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            result_data = [dict(zip(columns, row)) for row in rows]
            summary = None
            if output_json:
                with open(output_json, 'w') as f:
                    json.dump(result_data, f, indent=2)
                if result_data:
                    summary = f"Wrote {len(result_data)} records to {output_json}. First record: {result_data[0]}"
                else:
                    summary = f"Wrote 0 records to {output_json}."
            if print_result or not output_json:
                result = f"Columns: {columns}\nRows: {rows}"
                if summary:
                    return summary + "\n" + result
                else:
                    return result
            else:
                return summary
        else:
            conn.commit()
            result = f"Query executed successfully. Rows affected: {cursor.rowcount}"
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        return f"Error executing SQL: {str(e)}"

def execute_ipython(code, print_result=False):
    """Execute Python code using IPython and return stdout, stderr, and rich output."""
    import base64
    import matplotlib.pyplot as plt
    import matplotlib
    
    # Set matplotlib backend to Agg for non-interactive use
    matplotlib.use('Agg')
    
    shell = InteractiveShell.instance()
    output_buffer = io.StringIO()
    error_buffer = io.StringIO()
    rich_output = ""
    plots = []
    
    try:
        # Clear any existing plots
        plt.close('all')
        
        # Execute code with output capture
        with capture_output() as cap:
            with contextlib.redirect_stdout(output_buffer):
                with contextlib.redirect_stderr(error_buffer):
                    result = shell.run_cell(code, store_history=False)
        
        # Capture any matplotlib plots that were created
        if plt.get_fignums():  # Check if any figures exist
            for fig_num in plt.get_fignums():
                fig = plt.figure(fig_num)
                # Save plot to a BytesIO buffer
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
                buf.seek(0)
                # Convert to base64
                plot_data = base64.b64encode(buf.read()).decode('utf-8')
                plots.append(plot_data)
                buf.close()
            plt.close('all')  # Clean up
        
        # Collect outputs
        stdout = output_buffer.getvalue()
        stderr = error_buffer.getvalue()
        
        # Rich output (display_data, etc.)
        if cap.outputs:
            for out in cap.outputs:
                if hasattr(out, 'data') and 'text/plain' in out.data:
                    rich_output += out.data['text/plain'] + "\n"
        
        # If there's a result value, show it
        if result.result is not None:
            rich_output += repr(result.result) + "\n"
        
        # Build output with cleaner formatting
        output_sections = []
        
        if stdout.strip():
            output_sections.append(f"STDOUT:\n{stdout}")
            
        if stderr.strip():
            output_sections.append(f"STDERR:\n{stderr}")
            
        if rich_output.strip():
            output_sections.append(f"OUTPUT:\n{rich_output}")
            
        if plots:
            output_sections.append(f"PLOTS:\n{len(plots)} plot(s) generated")
            
        # Join sections with proper spacing
        output_text = "\n\n".join(output_sections) if output_sections else "No output"
            
        if print_result:
            print(f"IPython output:\n{output_text}")
            
        return output_text, plots
        
    except Exception as e:
        return f"Error executing Python code: {str(e)}", []

def apply_unified_diff(file_path, diff):
    """Apply a unified diff to a file with robust parsing and error handling. Returns a result string."""
    try:
        # Validate patch format first
        validation_error = _validate_patch_format(diff)
        if validation_error:
            return f"Invalid patch format: {validation_error}"
        
        # Try built-in implementation first
        try:
            return _apply_patch_builtin(file_path, diff)
        except Exception as builtin_error:
            # Fall back to external library if available
            try:
                return _apply_patch_external(file_path, diff)
            except ImportError:
                return f"Patch application failed: {str(builtin_error)}. Consider installing python-patch library: pip install patch"
            except Exception as external_error:
                return f"Both built-in and external patch methods failed. Built-in error: {str(builtin_error)}. External error: {str(external_error)}"
                
    except Exception as e:
        return f"Error applying diff: {str(e)}"

def _validate_patch_format(diff):
    """Validate unified diff format and return error message if invalid."""
    import re
    
    if not diff.strip():
        return "Empty patch content"
    
    lines = diff.split('\n')
    hunk_count = 0
    
    for i, line in enumerate(lines):
        # Check for hunk headers
        if line.startswith('@@'):
            if not re.match(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@', line):
                return f"Invalid hunk header format at line {i+1}: {line}"
            hunk_count += 1
        # Check line prefixes in hunks
        elif hunk_count > 0 and line and line[0] not in ' +-\\':
            return f"Invalid line prefix at line {i+1}: '{line[0]}' (expected ' ', '+', '-', or '\\')"
    
    if hunk_count == 0:
        return "No valid hunks found in patch"
    
    return None

def _apply_patch_builtin(file_path, diff):
    """Built-in patch application with detailed error handling."""
    # Parse the patch
    hunks = _parse_unified_diff(diff)
    if not hunks:
        raise Exception("No valid hunks parsed from diff")
    
    # Read the original file
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                original_lines = f.readlines()
        else:
            # Handle new file creation
            original_lines = []
    except Exception as e:
        raise Exception(f"Failed to read file {file_path}: {str(e)}")
    
    # Apply each hunk
    modified_lines = original_lines[:]
    line_offset = 0  # Track line number changes from previous hunks
    
    for hunk in hunks:
        try:
            modified_lines, new_offset = _apply_hunk(modified_lines, hunk, line_offset)
            line_offset += new_offset
        except Exception as e:
            raise Exception(f"Failed to apply hunk at line {hunk['old_start']}: {str(e)}")
    
    # Write the modified file
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(modified_lines)
        return f"Successfully applied patch to {file_path} ({len(hunks)} hunk(s))"
    except Exception as e:
        raise Exception(f"Failed to write modified file: {str(e)}")

def _parse_unified_diff(diff):
    """Parse unified diff into structured hunks."""
    import re
    
    lines = diff.split('\n')
    hunks = []
    current_hunk = None
    
    for line in lines:
        if line.startswith('@@'):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
            if match:
                if current_hunk:
                    hunks.append(current_hunk)
                
                old_start = int(match.group(1))
                old_count = int(match.group(2)) if match.group(2) else 1
                new_start = int(match.group(3)) 
                new_count = int(match.group(4)) if match.group(4) else 1
                
                current_hunk = {
                    'old_start': old_start,
                    'old_count': old_count,
                    'new_start': new_start,
                    'new_count': new_count,
                    'lines': []
                }
        elif current_hunk is not None:
            # Add lines to current hunk
            if line.startswith(' ') or line.startswith('+') or line.startswith('-'):
                current_hunk['lines'].append(line)
            elif line.startswith('\\'):
                # Handle "No newline at end of file"
                current_hunk['lines'].append(line)
    
    if current_hunk:
        hunks.append(current_hunk)
    
    return hunks

def _apply_hunk(lines, hunk, line_offset):
    """Apply a single hunk to the file lines."""
    # Adjust for 0-based indexing and previous hunks
    start_line = hunk['old_start'] - 1 + line_offset
    
    # Extract old and new content from hunk
    old_lines = []
    new_lines = []
    
    for line in hunk['lines']:
        if line.startswith(' '):
            # Context line
            old_lines.append(line[1:] + '\n')
            new_lines.append(line[1:] + '\n')
        elif line.startswith('-'):
            # Removed line
            old_lines.append(line[1:] + '\n')
        elif line.startswith('+'):
            # Added line
            new_lines.append(line[1:] + '\n')
        elif line.startswith('\\'):
            # Handle "No newline at end of file"
            if old_lines and old_lines[-1].endswith('\n'):
                old_lines[-1] = old_lines[-1][:-1]
            if new_lines and new_lines[-1].endswith('\n'):
                new_lines[-1] = new_lines[-1][:-1]
    
    # Validate that old content matches
    end_line = start_line + len(old_lines)
    if end_line > len(lines):
        raise Exception(f"Hunk extends beyond file (line {end_line} > {len(lines)})")
    
    actual_old = lines[start_line:end_line]
    if actual_old != old_lines:
        # Try fuzzy matching for minor whitespace differences
        if len(actual_old) == len(old_lines):
            for i, (actual, expected) in enumerate(zip(actual_old, old_lines)):
                if actual.strip() != expected.strip():
                    raise Exception(f"Content mismatch at line {start_line + i + 1}. Expected: {repr(expected.strip())}, Got: {repr(actual.strip())}")
        else:
            raise Exception(f"Line count mismatch. Expected {len(old_lines)} lines, got {len(actual_old)}")
    
    # Apply the change
    lines[start_line:end_line] = new_lines
    
    # Return modified lines and the offset change for subsequent hunks
    offset_change = len(new_lines) - len(old_lines)
    return lines, offset_change

def _apply_patch_external(file_path, diff):
    """Apply patch using external python-patch library as fallback."""
    import patch
    
    try:
        # Write the diff to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8', suffix='.patch') as tmp_patch:
            tmp_patch.write(diff)
            patch_path = tmp_patch.name
        
        # Apply the patch
        pset = patch.fromfile(patch_path)
        if not pset:
            os.unlink(patch_path)
            raise Exception("Failed to parse patch file with external library")
        
        result = pset.apply()
        os.unlink(patch_path)
        
        if result:
            return f"Applied patch to {file_path} using external library"
        else:
            raise Exception("External library failed to apply patch")
            
    except Exception as e:
        if 'patch_path' in locals() and os.path.exists(patch_path):
            os.unlink(patch_path)
        raise e

def overwrite_file(file_path, content):
    """Overwrite a file with new content."""
    try:
        with open(file_path, 'w') as f:
            f.write(content)
        return f"Overwrote {file_path} with new content."
    except Exception as e:
        return f"Error overwriting file: {str(e)}"

def read_file(file_path):
    """Read a file and return its contents with line numbers for LLM reference."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Format with line numbers, similar to cat -n but using → for better visibility
        numbered_lines = []
        for i, line in enumerate(lines, 1):
            # Remove trailing newline for formatting, we'll add it back
            line_content = line.rstrip('\n\r')
            numbered_lines.append(f"{i:4d}→{line_content}")
        
        result = '\n'.join(numbered_lines)
        return f"Contents of {file_path}:\n{result}"
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"

def search_files(pattern, path, file_extensions=None, ignore_dirs=None, case_sensitive=False, regex=False, max_results=100):
    """Search for text patterns across files with line numbers."""
    import re
    
    # Default ignore directories
    default_ignore_dirs = {'.git', '__pycache__', 'node_modules', '.svn', '.hg', 'venv', 'env', 'build', 'dist', '.tox'}
    ignore_dirs = set(ignore_dirs or []) | default_ignore_dirs
    
    # Prepare pattern
    if regex:
        try:
            pattern_obj = re.compile(pattern, re.IGNORECASE if not case_sensitive else 0)
        except re.error as e:
            return f"Error: Invalid regex pattern '{pattern}': {str(e)}"
    else:
        # Escape special regex characters for literal search
        escaped_pattern = re.escape(pattern)
        pattern_obj = re.compile(escaped_pattern, re.IGNORECASE if not case_sensitive else 0)
    
    matches = []
    files_searched = 0
    
    def should_include_file(filepath):
        """Check if file should be included based on extensions."""
        if not file_extensions:
            return True
        file_ext = os.path.splitext(filepath)[1].lstrip('.')
        return file_ext in file_extensions
    
    def is_text_file(filepath):
        """Basic check if file is likely a text file."""
        try:
            with open(filepath, 'rb') as f:
                chunk = f.read(1024)
                return b'\x00' not in chunk  # Binary files often contain null bytes
        except:
            return False
    
    def search_file(filepath):
        """Search within a single file."""
        nonlocal files_searched
        try:
            if not should_include_file(filepath) or not is_text_file(filepath):
                return []
            
            files_searched += 1
            file_matches = []
            
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    line_content = line.rstrip('\n\r')
                    if pattern_obj.search(line_content):
                        file_matches.append({
                            'file': filepath,
                            'line_num': line_num,
                            'line_content': line_content,
                            'match': pattern_obj.search(line_content).group(0)
                        })
                        
                        if len(matches) + len(file_matches) >= max_results:
                            break
            
            return file_matches
            
        except Exception as e:
            return [{'file': filepath, 'error': str(e)}]
    
    try:
        if os.path.isfile(path):
            # Search single file
            matches = search_file(path)
        elif os.path.isdir(path):
            # Search directory recursively
            for root, dirs, files in os.walk(path):
                # Remove ignored directories from dirs list to prevent walking into them
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                
                for file in files:
                    filepath = os.path.join(root, file)
                    file_matches = search_file(filepath)
                    matches.extend(file_matches)
                    
                    if len(matches) >= max_results:
                        break
                
                if len(matches) >= max_results:
                    break
        else:
            return f"Error: Path '{path}' does not exist"
        
        # Format results
        if not matches:
            search_type = "file" if os.path.isfile(path) else "directory"
            return f"No matches found for pattern '{pattern}' in {search_type} '{path}' (searched {files_searched} files)"
        
        result_lines = [f"Search results for pattern '{pattern}' in '{path}':"]
        result_lines.append(f"Found {len(matches)} matches in {files_searched} files searched")
        result_lines.append("")
        
        current_file = None
        for match in matches[:max_results]:
            if 'error' in match:
                result_lines.append(f"Error in {match['file']}: {match['error']}")
                continue
                
            if match['file'] != current_file:
                current_file = match['file']
                result_lines.append(f"=== {current_file} ===")
            
            result_lines.append(f"{match['line_num']:4d}→{match['line_content']}")
        
        if len(matches) >= max_results:
            result_lines.append(f"\n... (truncated at {max_results} results)")
        
        return "\n".join(result_lines)
        
    except Exception as e:
        return f"Error searching files: {str(e)}"

def get_current_memory_manager():
    """Get the memory manager for the current session."""
    from flask import session as flask_session
    session_id = flask_session.get('session_id')
    if session_id and session_id in sessions:
        return sessions[session_id]['memory_manager']
    return MemoryManager()  # Fallback to default

def save_memory(title, content, tags=None):
    """Save a memory using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memory_id = memory_manager.save_memory(title, content, tags or [])
        return f"Memory saved successfully with ID: {memory_id}\nTitle: {title}"
    except Exception as e:
        return f"Error saving memory: {str(e)}"

def search_memory(query=None, tags=None, limit=10):
    """Search memories using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memories = memory_manager.search_memories(query, tags, limit)
        
        if not memories:
            return "No memories found matching the search criteria."
        
        result_lines = [f"Found {len(memories)} memories:"]
        for memory in memories:
            result_lines.append(f"\nID: {memory['id']}")
            result_lines.append(f"Title: {memory['title']}")
            if memory['tags']:
                result_lines.append(f"Tags: {', '.join(memory['tags'])}")
            result_lines.append(f"Content: {memory['content']}")
            result_lines.append(f"Created: {memory['created_at']}")
            result_lines.append("---")
        
        return "\n".join(result_lines)
    except ValueError as e:
        # Return the error as a tool result so the agent can recover
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching memories: {str(e)}"

def list_memories(limit=20, offset=0):
    """List memories using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memories = memory_manager.list_memories(limit, offset)
        
        if not memories:
            return "No memories found."
        
        result_lines = [f"Listing {len(memories)} memories (limit: {limit}, offset: {offset}):"]
        for memory in memories:
            result_lines.append(f"\nID: {memory['id']}")
            result_lines.append(f"Title: {memory['title']}")
            if memory['tags']:
                result_lines.append(f"Tags: {', '.join(memory['tags'])}")
            # Truncate content for list view
            content_preview = memory['content'][:100] + "..." if len(memory['content']) > 100 else memory['content']
            result_lines.append(f"Content: {content_preview}")
            result_lines.append(f"Created: {memory['created_at']}")
            result_lines.append("---")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error listing memories: {str(e)}"

def get_memory(memory_id):
    """Get a specific memory using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        memory = memory_manager.get_memory(memory_id)
        
        if not memory:
            return f"Memory with ID {memory_id} not found."
        
        result_lines = [
            f"Memory ID: {memory['id']}",
            f"Title: {memory['title']}",
            f"Content: {memory['content']}"
        ]
        
        if memory['tags']:
            result_lines.append(f"Tags: {', '.join(memory['tags'])}")
        
        result_lines.extend([
            f"Created: {memory['created_at']}",
            f"Updated: {memory['updated_at']}",
            f"Last Accessed: {memory['accessed_at']}"
        ])
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving memory: {str(e)}"

def delete_memory(memory_id):
    """Delete a memory using the current session's memory manager."""
    try:
        memory_manager = get_current_memory_manager()
        success = memory_manager.delete_memory(memory_id)
        
        if success:
            return f"Memory with ID {memory_id} deleted successfully."
        else:
            return f"Memory with ID {memory_id} not found or could not be deleted."
    except Exception as e:
        return f"Error deleting memory: {str(e)}"

def get_current_todo_manager():
    """Get the todo manager for the current session."""
    from flask import session as flask_session
    session_id = flask_session.get('session_id')
    if session_id and session_id in sessions:
        return sessions[session_id]['todo_manager']
    return TodoManager()  # Fallback to default

def create_todo(title, description="", priority="medium", project=None, due_date=None, tags=None, estimated_hours=None):
    """Create a new todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todo_id = todo_manager.create_todo(
            title=title,
            description=description,
            priority=priority,
            project=project,
            due_date=due_date,
            tags=tags or [],
            estimated_hours=estimated_hours
        )
        return f"Todo created successfully with ID: {todo_id}\nTitle: {title}\nPriority: {priority}"
    except Exception as e:
        return f"Error creating todo: {str(e)}"

def update_todo(todo_id, **kwargs):
    """Update a todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        success = todo_manager.update_todo(todo_id, **kwargs)
        
        if success:
            updated_fields = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"Todo {todo_id} updated successfully.\nUpdated: {updated_fields}"
        else:
            return f"Todo with ID {todo_id} not found or could not be updated."
    except Exception as e:
        return f"Error updating todo: {str(e)}"

def list_todos(state=None, priority=None, project=None, limit=20):
    """List todos using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todos = todo_manager.list_todos(
            state=state,
            priority=priority,
            project=project,
            limit=limit
        )
        
        if not todos:
            filter_desc = []
            if state: filter_desc.append(f"state={state}")
            if priority: filter_desc.append(f"priority={priority}")
            if project: filter_desc.append(f"project={project}")
            filters = f" ({', '.join(filter_desc)})" if filter_desc else ""
            return f"No todos found{filters}."
        
        result_lines = [f"Found {len(todos)} todos:"]
        for todo in todos:
            status_emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(todo['state'], "📋")
            priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
            
            result_lines.append(f"\n{status_emoji} {priority_emoji} [{todo['state'].upper()}] {todo['title']}")
            result_lines.append(f"   ID: {todo['id']}")
            
            if todo['description']:
                desc_preview = todo['description'][:100] + "..." if len(todo['description']) > 100 else todo['description']
                result_lines.append(f"   Description: {desc_preview}")
            
            if todo['project']:
                result_lines.append(f"   Project: {todo['project']}")
            
            if todo['due_date']:
                result_lines.append(f"   Due: {todo['due_date']}")
            
            result_lines.append(f"   Created: {todo['created_at']}")
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error listing todos: {str(e)}"

def get_kanban_board(project=None):
    """Get kanban board view using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        board = todo_manager.get_kanban_board(project=project)
        
        result_lines = ["=== KANBAN BOARD ==="]
        if project:
            result_lines[0] += f" (Project: {project})"
        
        for state, todos in board.items():
            state_title = state.replace("_", " ").title()
            emoji = {"Todo": "📋", "In Progress": "🔄", "Completed": "✅"}[state_title]
            result_lines.append(f"\n{emoji} {state_title} ({len(todos)} items):")
            result_lines.append("=" * 30)
            
            if not todos:
                result_lines.append("   (no items)")
            else:
                for todo in todos[:10]:  # Show max 10 per column
                    priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
                    result_lines.append(f"   {priority_emoji} {todo['title']} (ID: {todo['id'][:8]})")
                    
                if len(todos) > 10:
                    result_lines.append(f"   ... and {len(todos) - 10} more")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error getting kanban board: {str(e)}"

def search_todos(query, include_completed=False):
    """Search todos using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todos = todo_manager.search_todos(query, include_completed)
        
        if not todos:
            return f"No todos found matching '{query}'."
        
        result_lines = [f"Found {len(todos)} todos matching '{query}':"]
        for todo in todos:
            status_emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(todo['state'], "📋")
            priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
            
            result_lines.append(f"\n{status_emoji} {priority_emoji} {todo['title']}")
            result_lines.append(f"   ID: {todo['id']}")
            result_lines.append(f"   State: {todo['state']}")
            if todo['description']:
                desc_preview = todo['description'][:100] + "..." if len(todo['description']) > 100 else todo['description']
                result_lines.append(f"   Description: {desc_preview}")
            
        return "\n".join(result_lines)
    except ValueError as e:
        # Return the error as a tool result so the agent can recover
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching todos: {str(e)}"

def get_todo(todo_id):
    """Get a specific todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        todo = todo_manager.get_todo(todo_id)
        
        if not todo:
            return f"Todo with ID {todo_id} not found."
        
        status_emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(todo['state'], "📋")
        priority_emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(todo['priority'], "🟡")
        
        result_lines = [
            f"{status_emoji} {priority_emoji} {todo['title']}",
            f"ID: {todo['id']}",
            f"State: {todo['state']}",
            f"Priority: {todo['priority']}"
        ]
        
        if todo['description']:
            result_lines.append(f"Description: {todo['description']}")
        
        if todo['project']:
            result_lines.append(f"Project: {todo['project']}")
        
        if todo['due_date']:
            result_lines.append(f"Due Date: {todo['due_date']}")
        
        if todo['tags']:
            result_lines.append(f"Tags: {', '.join(todo['tags'])}")
        
        if todo['estimated_hours']:
            result_lines.append(f"Estimated Hours: {todo['estimated_hours']}")
        
        if todo['actual_hours']:
            result_lines.append(f"Actual Hours: {todo['actual_hours']}")
        
        result_lines.extend([
            f"Created: {todo['created_at']}",
            f"Updated: {todo['updated_at']}"
        ])
        
        if todo['completed_at']:
            result_lines.append(f"Completed: {todo['completed_at']}")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving todo: {str(e)}"

def delete_todo(todo_id):
    """Delete a todo using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        success = todo_manager.delete_todo(todo_id)
        
        if success:
            return f"Todo with ID {todo_id} deleted successfully."
        else:
            return f"Todo with ID {todo_id} not found or could not be deleted."
    except Exception as e:
        return f"Error deleting todo: {str(e)}"

def get_todo_stats(project=None):
    """Get todo statistics using the current session's todo manager."""
    try:
        todo_manager = get_current_todo_manager()
        stats = todo_manager.get_project_stats(project)
        
        result_lines = ["=== TODO STATISTICS ==="]
        if project:
            result_lines[0] += f" (Project: {project})"
        
        # State counts
        result_lines.append("\n📊 By State:")
        for state, count in stats['states'].items():
            emoji = {"todo": "📋", "in_progress": "🔄", "completed": "✅"}.get(state, "📋")
            result_lines.append(f"   {emoji} {state.replace('_', ' ').title()}: {count}")
        
        # Priority counts
        if stats['priorities']:
            result_lines.append("\n🎯 By Priority (active only):")
            for priority, count in stats['priorities'].items():
                emoji = {"low": "🔵", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(priority, "🟡")
                result_lines.append(f"   {emoji} {priority.title()}: {count}")
        
        # Overdue and total
        result_lines.append(f"\n⚠️  Overdue: {stats['overdue']}")
        result_lines.append(f"📈 Total: {stats['total']}")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error getting todo stats: {str(e)}"

def get_current_github_rag():
    """Get the current session's GitHub RAG instance."""
    try:
        from flask import session as flask_session
        session_id = flask_session.get('session_id')
        if session_id and session_id in sessions:
            if 'github_rag' not in sessions[session_id]:
                # Initialize GitHub RAG with OpenAI API key
                openai_api_key = os.environ.get("OPENAI_API_KEY")
                if not openai_api_key:
                    raise ValueError("OPENAI_API_KEY environment variable not found")
                sessions[session_id]['github_rag'] = GitHubRAG(openai_api_key)
            return sessions[session_id]['github_rag']
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
                socketio.emit('rag_index_progress', progress_data, room=session_id)
        
        result = github_rag.index_repository(
            repo_url=repo_url,
            include_extensions=include_extensions,
            ignore_dirs=ignore_dirs,
            progress_callback=progress_callback
        )
        
        if result['success']:
            # Add to memory for context
            memory_manager = get_current_memory_manager()
            memory_manager.save_memory(
                title=f"GitHub Repository Indexed: {result['repo_name']}",
                content=f"Repository: {repo_url}\nCollection: {result['collection_name']}\nDocuments: {result.get('document_count', 0)}\nChunks: {result.get('chunk_count', 0)}",
                tags=['github_rag', 'repository', result['repo_name']]
            )
            
            # Refresh system prompt to include the new repository
            session_id = get_current_session_id()
            if session_id and session_id in sessions:
                llm = sessions[session_id]['llm']
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
            collection_name=collection_name,
            question=question,
            max_results=max_results
        )
        
        if result['success']:
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
            
            for citation in result['citations']:
                output_lines.append(f"\n[{citation['source_id']}] {citation['file_path']}")
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
            output_lines.extend([
                f"📁 {repo['repo_name']}",
                f"   Collection: {repo['collection_name']}",
                f"   URL: {repo['repo_url']}",
                f"   Files: {repo['document_count']} | Chunks: {repo['chunk_count']}",
                ""
            ])
        
        output_lines.append("💡 Use github_rag_query with the collection name to ask questions about any repository.")
        
        return "\n".join(output_lines)
        
    except Exception as e:
        return f"Error listing repositories: {str(e)}"


class LLM:
    def __init__(self, model, session_id=None):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise ValueError("ANTHROPIC_API_KEY environment variable not found.")
        self.client = anthropic.Anthropic(
            
        )
        self.model = model
        self.session_id = session_id
        self.messages = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
        self.system_prompt = self._build_system_prompt()
        self.tools = [bash_tool, sqlite_tool, ipython_tool, edit_file_diff_tool, overwrite_file_tool, read_file_tool, search_files_tool, save_memory_tool, search_memory_tool, list_memories_tool, get_memory_tool, delete_memory_tool, create_todo_tool, update_todo_tool, list_todos_tool, get_kanban_board_tool, search_todos_tool, get_todo_tool, delete_todo_tool, get_todo_stats_tool, github_rag_index_tool, github_rag_query_tool, github_rag_list_tool]
    
    def _build_system_prompt(self):
        """Build the system prompt dynamically including RAG repository information."""
        base_prompt = (
            """You are a helpful AI assistant with access to bash, sqlite, Python, and file editing tools.\n"""
            "You can help the user by executing commands and interpreting the results.\n"
            "Be careful with destructive commands and always explain what you're doing.\n\n"
            
            "AVAILABLE TOOLS:\n"
            "- bash: Run shell commands with configurable timeout and streaming\n"
            "- sqlite: Execute SQL queries on SQLite databases\n"
            "- ipython: Execute Python code with rich output support\n"
            "- edit_file_diff: Apply unified diff patches to files\n"
            "- overwrite_file: Replace entire file contents\n"
            "- read_file: Read file contents with line numbers\n"
            "- search_files: Search for text patterns across files with line numbers (supports regex, file filters, recursive directory search)\n"
            "- Memory tools: save_memory, search_memory, list_memories, get_memory, delete_memory\n"
            "- Todo/Task tools: create_todo, update_todo, list_todos, get_kanban_board, search_todos, get_todo, delete_todo, get_todo_stats\n\n"
            
            "FILE EDITING GUIDELINES:\n"
            "- Use edit_file_diff for precise, contextual changes with unified diff format\n"
            "- Use overwrite_file for complete file replacement or new file creation\n"
            "- The edit_file_diff tool has robust error handling and supports both git-style and traditional diffs\n"
            "- Always include sufficient context (3+ lines) in patches for reliable application\n"
            "- For multiple small changes, consider using separate patches or overwrite_file\n\n"
            
            "SQLITE USAGE:\n"
            "For large SELECT queries, you can specify an 'output_json' file path in the sqlite tool input. If you do, write the full result to that file and only print errors or the first record in the response.\n"
            "You can also set 'print_result' to true to print the results in the context window, even if output_json is specified. This is useful for letting you see and reason about the data in context.\n\n"
            
            "PYTHON ENVIRONMENT:\n"
            "When generating plots in Python (e.g., with matplotlib), always save the plot to a file (such as .png) and mention the filename in your response. Do not attempt to display plots inline.\n"
            "The Python environment for the ipython tool includes: numpy, matplotlib, scikit-learn, ipykernel, torch, tqdm, gymnasium, torchvision, tensorboard, torch-tb-profiler, opencv-python, nbconvert, anthropic, seaborn, pandas, tenacity.\n\n"
            
            "MEMORY USAGE:\n"
            "Use the memory tools to store and retrieve important information across conversations:\n"
            "- save_memory: Store important facts, solutions, configurations, or insights\n"
            "- search_memory: Find relevant information from previous sessions\n"
            "- list_memories: Browse all stored memories\n"
            "- get_memory: Retrieve a specific memory by ID\n"
            "- delete_memory: Remove outdated or incorrect memories\n"
            "Always check for relevant memories before starting complex tasks to leverage previous work.\n\n"
            
            "TODO/TASK MANAGEMENT:\n"
            "Use the todo tools to break down complex work and track progress with kanban workflow:\n"
            "- create_todo: Break complex tasks into manageable todos with priorities and due dates\n"
            "- update_todo: Move todos between states (todo/in_progress/completed) and update details\n"
            "- list_todos: View current work filtered by state, priority, or project\n"
            "- get_kanban_board: See organized kanban board view of all tasks\n"
            "- search_todos: Find specific todos by title or description\n"
            "- get_todo_stats: Get overview of workload and progress\n"
            "ALWAYS create todos for multi-step tasks and update states as you work. Use 'in_progress' for current work.\n\n"
            
            "GITHUB RAG (REPOSITORY ANALYSIS):\n"
            "Use GitHub RAG tools to index and query external repositories for code analysis:\n"
            "- github_rag_index: Clone and index a GitHub repository for searchable analysis\n"
            "- github_rag_query: Ask questions about indexed repositories with citations\n"
            "- github_rag_list: List all indexed repositories and their collection names\n"
            "When a repository is indexed, it's automatically saved to memory for context. Query results include specific file references and code snippets with citations.\n\n"
            
            "when you are asked to do something, you should first check the memory for relevant information, and if you don't find it, you should use the tools to get the information you need."
            "after searching memory and rag, create a plan and add it to your todos."
            "if you find a problem along the, update your todos to track the problem, but make sure you stay on the overall goal."
        )
        
        # Add RAG repository information if available
        rag_info = self._get_rag_repositories_info()
        if rag_info:
            base_prompt += rag_info + "\n\n"
            
        # add all memory titles to the system prompt
        memory_manager = get_current_memory_manager()
        memory_titles = [memory['title'] for memory in memory_manager.list_memories(limit=100)]
        if memory_titles:
            base_prompt += "MEMORY TITLES:\n"
            for title in memory_titles:
                base_prompt += f"- {title}\n"
            
        # Add custom system prompt if configured
        if 'SYSTEM_PROMPT' in app.config and app.config['SYSTEM_PROMPT']:
            base_prompt += app.config['SYSTEM_PROMPT']
            
        print("SYSTEM PROMPT:", base_prompt)
            
        return base_prompt
    
    def _get_rag_repositories_info(self):
        """Get information about available RAG repositories."""
        try:
            if self.session_id and self.session_id in sessions:
                if 'github_rag' not in sessions[self.session_id]:
                    # Try to initialize GitHub RAG to check for existing repositories
                    openai_api_key = os.environ.get("OPENAI_API_KEY")
                    if openai_api_key:
                        sessions[self.session_id]['github_rag'] = GitHubRAG(openai_api_key)
                    else:
                        return None
                
                github_rag = sessions[self.session_id]['github_rag']
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
        reraise=True
    )
    def _call_anthropic(self, stream=False):
        return self.client.messages.create(
            model=self.model,
            max_tokens=64_000,
            system=self.system_prompt,
            messages=self.messages,
            tools=self.tools,
            stream=stream,
            timeout=600.0  # 10 minutes timeout for long operations
        )

    def summarize_image(self, image_data, filename):
        """Summarize an image using a separate LLM call to save tokens."""
        print(f"Summarizing image: {filename}")
        
        # Create a simple client for image summarization
        temp_messages = [{
            "role": "user", 
            "content": [
                {
                    "type": "text",
                    "text": f"Please provide a detailed description of this image ({filename}). Focus on the key visual elements, text content, UI elements, code, diagrams, or any other important details that would be useful for an AI assistant helping with programming tasks."
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data
                    }
                }
            ]
        }]
        
        try:
            response = self.client.messages.create(
                model="claude-opus-4-1-20250805",  # Use latest Claude for best image understanding
                max_tokens=1000,
                system="You are an expert at describing images in detail. Provide comprehensive descriptions that would help an AI assistant understand the content.",
                messages=temp_messages
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
                            tool_calls.append({
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": event.content_block.input
                            })
                    
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
                        if hasattr(event.delta, 'stop_reason'):
                            print(f"Stream finished: {event.delta.stop_reason}")
                    
                    elif event.type == "message_stop":
                        # Handle different API versions - some have usage directly on event
                        if hasattr(event, 'usage') and event.usage:
                            output_tokens = event.usage.output_tokens
                        elif hasattr(event, 'message') and hasattr(event.message, 'usage'):
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
                session_id = flask_session.get('session_id')
                if session_id:
                    emit('token_usage_update', {
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'total_input_tokens': self.total_input_tokens,
                        'total_output_tokens': self.total_output_tokens,
                        'total_tokens': self.total_tokens,
                        'timestamp': datetime.now().isoformat()
                    }, room=session_id)
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
                if isinstance(user_message.get("content"), list) and len(user_message["content"]) > 0:
                    last_content = user_message["content"][-1]
                    if isinstance(last_content, dict) and "cache_control" in last_content:
                        del last_content["cache_control"]
                        print(f"DEBUG: Removed cache_control from user message")
                break
    
    def _validate_message_structure(self):
        """Validate message structure to prevent orphaned tool_result blocks."""
        if not self.messages:
            return
            
        print(f"DEBUG: Validating message structure with {len(self.messages)} messages")
        
        # Print all messages for debugging
        for i, msg in enumerate(self.messages):
            print(f"DEBUG: Message {i}: role={msg.get('role')}, content_type={type(msg.get('content'))}")
            if isinstance(msg.get('content'), list):
                for j, content in enumerate(msg['content']):
                    content_type = content.get('type') if isinstance(content, dict) else getattr(content, 'type', 'unknown')
                    if content_type == 'tool_use':
                        tool_id = content.get('id') if isinstance(content, dict) else getattr(content, 'id', 'unknown')
                        print(f"DEBUG:   Content {j}: {content_type} with ID: {tool_id}")
                    elif content_type == 'tool_result':
                        tool_use_id = content.get('tool_use_id') if isinstance(content, dict) else getattr(content, 'tool_use_id', 'unknown')
                        print(f"DEBUG:   Content {j}: {content_type} with tool_use_id: {tool_use_id}")
                    else:
                        print(f"DEBUG:   Content {j}: {content_type}")
        
        # Check for orphaned tool_result blocks
        for i, message in enumerate(self.messages):
            if message.get("role") == "user" and isinstance(message.get("content"), list):
                tool_results = [c for c in message["content"] if c.get("type") == "tool_result"]
                if tool_results:
                    print(f"DEBUG: Found {len(tool_results)} tool_result blocks in message {i}")
                    
                    # Look for corresponding tool_use blocks in previous assistant messages
                    tool_use_ids = set()
                    
                    # Search backwards for the most recent assistant message with tool_use blocks
                    for j in range(i-1, -1, -1):
                        prev_message = self.messages[j]
                        print(f"DEBUG: Checking message {j}: role={prev_message.get('role')}")
                        
                        if prev_message.get("role") == "assistant":
                            prev_content = prev_message.get("content", [])
                            print(f"DEBUG: Assistant message content type: {type(prev_content)}")
                            if isinstance(prev_content, list):
                                for c in prev_content:
                                    if hasattr(c, 'type') and c.type == "tool_use":
                                        tool_id = getattr(c, 'id', None)
                                        if tool_id:
                                            tool_use_ids.add(tool_id)
                                            print(f"DEBUG: Found tool_use with ID: {tool_id}")
                                    elif isinstance(c, dict) and c.get("type") == "tool_use":
                                        tool_id = c.get("id")
                                        if tool_id:
                                            tool_use_ids.add(tool_id)
                                            print(f"DEBUG: Found tool_use with ID: {tool_id}")
                            break  # Stop at first assistant message found
                    
                    print(f"DEBUG: All valid tool_use IDs found: {tool_use_ids}")
                    
                    # If no tool_use blocks found, remove ALL tool_result blocks
                    if not tool_use_ids:
                        print(f"DEBUG: No tool_use blocks found - removing ALL {len(tool_results)} tool_result blocks")
                        original_count = len(message["content"])
                        valid_content = []
                        removed_count = 0
                        for content_block in message["content"]:
                            if content_block.get("type") == "tool_result":
                                print(f"DEBUG: Removing orphaned tool_result with ID: {content_block.get('tool_use_id')}")
                                removed_count += 1
                                continue
                            valid_content.append(content_block)
                        message["content"] = valid_content
                        print(f"DEBUG: Removed {removed_count} orphaned tool_results. Content blocks: {original_count} -> {len(valid_content)}")
                    else:
                        # Remove only orphaned tool_results
                        original_count = len(message["content"])
                        valid_content = []
                        removed_count = 0
                        for content_block in message["content"]:
                            if content_block.get("type") == "tool_result":
                                tool_result_id = content_block.get("tool_use_id")
                                print(f"DEBUG: Checking tool_result with ID: {tool_result_id}")
                                if tool_result_id not in tool_use_ids:
                                    print(f"DEBUG: Removing orphaned tool_result with ID: {tool_result_id}")
                                    removed_count += 1
                                    continue
                                else:
                                    print(f"DEBUG: Keeping valid tool_result with ID: {tool_result_id}")
                            valid_content.append(content_block)
                        message["content"] = valid_content
                        print(f"DEBUG: Removed {removed_count} orphaned tool_results. Content blocks: {original_count} -> {len(valid_content)}")

    def __call__(self, content, stream_callback=None):
        """Main call method with optional streaming support."""
        print(f"DEBUG: LLM.__call__ received content with {len(content)} items:")
        for i, item in enumerate(content):
            item_type = item.get('type') if isinstance(item, dict) else getattr(item, 'type', 'unknown')
            print(f"DEBUG:   Item {i}: {item_type}")
            if item_type == 'tool_result':
                tool_use_id = item.get('tool_use_id') if isinstance(item, dict) else getattr(item, 'tool_use_id', 'unknown')
                print(f"DEBUG:     tool_use_id: {tool_use_id}")
        
        self.messages.append({"role": "user", "content": content})
        
        # Add cache control to the last content item if it exists
        user_message = self.messages[-1]
        if user_message.get("content") and len(user_message["content"]) > 0:
            user_message["content"][-1]["cache_control"] = {"type": "ephemeral"}
        
        # Validate message structure to prevent orphaned tool_result blocks
        # This must happen AFTER adding the user message since tool_results are in the new message
        self._validate_message_structure()
        
        try:
            # Use streaming if callback provided
            if stream_callback:
                # Get response from streaming
                response_text, tool_calls = self._call_with_streaming(stream_callback)
                
                # Build assistant message for streaming response
                assistant_response = {"role": "assistant", "content": []}
                
                # Add text content if any
                if response_text:
                    assistant_response["content"].append({"type": "text", "text": response_text})
                
                # Add tool_use blocks
                for tool_call in tool_calls:
                    # Create a proper tool_use content block as a dict
                    tool_use_block = {
                        'type': 'tool_use',
                        'id': tool_call['id'],
                        'name': tool_call['name'],
                        'input': tool_call['input']
                    }
                    assistant_response["content"].append(tool_use_block)
                
                # Append assistant message to conversation history
                print(f"DEBUG: Appending streaming assistant response. Messages before: {len(self.messages)}")
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
        if hasattr(response, 'usage'):
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.total_tokens = self.total_input_tokens + self.total_output_tokens
            
            # Emit token usage update to web client
            try:
                from flask import session as flask_session
                session_id = flask_session.get('session_id')
                if session_id:
                    emit('token_usage_update', {
                        'input_tokens': response.usage.input_tokens,
                        'output_tokens': response.usage.output_tokens,
                        'total_input_tokens': self.total_input_tokens,
                        'total_output_tokens': self.total_output_tokens,
                        'total_tokens': self.total_tokens,
                        'timestamp': datetime.now().isoformat()
                    }, room=session_id)
            except:
                pass  # Ignore if not in web context
        
        assistant_response = {"role": "assistant", "content": []}
        tool_calls = []
        output_text = ""

        for content in response.content:
            if content.type == "text":
                text_content = content.text
                output_text += text_content
                assistant_response["content"].append({"type": "text", "text": text_content})
                print(f"DEBUG: Adding text content to assistant response: {len(text_content)} chars")
            elif content.type == "tool_use":
                assistant_response["content"].append(content)
                tool_calls.append({
                    "id": content.id,
                    "name": content.name,
                    "input": content.input
                })
                print(f"DEBUG: Adding tool_use to assistant response: {content.name} with ID: {content.id}")

        print(f"DEBUG: Appending assistant response to messages. Total messages before: {len(self.messages)}")
        print(f"DEBUG: Assistant response content blocks: {len(assistant_response['content'])}")
        for i, content in enumerate(assistant_response['content']):
            content_type = content.get('type') if isinstance(content, dict) else getattr(content, 'type', 'unknown')
            print(f"DEBUG:   Assistant content {i}: {content_type}")
        
        self.messages.append(assistant_response)
        print(f"DEBUG: Total messages after adding assistant response: {len(self.messages)}")
        return output_text, tool_calls


if __name__ == "__main__":
    main()