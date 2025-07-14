import os
import json
from flask import Blueprint, render_template, request, jsonify, current_app

# Create a Blueprint for Monaco editor routes
monaco_bp = Blueprint('monaco', __name__)

@monaco_bp.route('/monaco')
def monaco_editor():
    """Render the Monaco editor page"""
    return render_template('monaco.html')

@monaco_bp.route('/api/monaco/files')
def list_files():
    """API endpoint to list files for Monaco editor"""
    try:
        # Get the current working directory
        base_dir = os.getcwd()
        
        # Get all files in the current directory (non-recursive)
        files = []
        for item in os.listdir(base_dir):
            # Skip hidden files/directories
            if item.startswith('.'):
                continue
                
            item_path = os.path.join(base_dir, item)
            is_dir = os.path.isdir(item_path)
            
            files.append({
                'name': item,
                'path': item,
                'isDirectory': is_dir
            })
        
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@monaco_bp.route('/api/monaco/file')
def get_file():
    """API endpoint to get file content for Monaco editor"""
    file_path = request.args.get('path')
    if not file_path:
        return jsonify({'error': 'No file path provided'}), 400
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': f'Error reading file: {str(e)}'}), 500

@monaco_bp.route('/api/monaco/save', methods=['POST'])
def save_file():
    """API endpoint to save file content from Monaco editor"""
    try:
        data = request.json
        if not data or 'path' not in data or 'content' not in data:
            return jsonify({'error': 'Invalid request data'}), 400
            
        file_path = data['path']
        content = data['content']
        
        # Check if the directory exists, create it if needed
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500