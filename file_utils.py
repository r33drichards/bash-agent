"""Utility functions for file operations in bash-agent"""

import os
import io
import shutil


DEFAULT_CHUNK_SIZE = 16 * 1024


def get_file_extension(filename):
    """Get the extension of a file without the leading dot"""
    ext = os.path.splitext(filename)[1]
    if ext.startswith('.'):
        ext = ext[1:]
    return ext.lower()


def write_file(content, filepath, encoding='utf-8', newline='\n', chunk_size=None):
    """Write content to a file with error handling
    
    Args:
        content (str): Content to write to the file
        filepath (str): Path to the file
        encoding (str, optional): File encoding. Defaults to 'utf-8'.
        newline (str, optional): Newline character. Defaults to '\n'.
        chunk_size (int, optional): Chunk size for writing. Defaults to None.
        
    Returns:
        tuple: (success, message)
    """
    success = True
    message = 'File saved successfully'
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            
        if isinstance(content, str):
            content_buffer = io.StringIO(content, newline=newline)
            with io.open(filepath, 'w', encoding=encoding, newline=newline) as dest:
                content_buffer.seek(0)
                try:
                    shutil.copyfileobj(content_buffer, dest, chunk_size or DEFAULT_CHUNK_SIZE)
                except OSError as err:
                    success = False
                    message = 'Could not save file: ' + str(err)
        else:
            success = False
            message = 'Could not save file: Invalid content'
    except Exception as e:
        success = False
        message = f'Could not save file: {str(e)}'
    return success, message


def dir_tree(abs_path, exclude_names=None, excluded_extensions=None, allowed_extensions=None):
    """Generate a directory tree structure
    
    Args:
        abs_path (str): Absolute path to the directory
        exclude_names (list, optional): List of file/dir names to exclude. Defaults to None.
        excluded_extensions (list, optional): List of file extensions to exclude. Defaults to None.
        allowed_extensions (list, optional): List of allowed file extensions. Defaults to None.
        
    Returns:
        list: List of dictionaries representing the directory tree
    """
    if exclude_names is None:
        exclude_names = ['.git', '__pycache__', '.venv', 'node_modules', '.idea', '.vscode']
        
    result = []
    
    try:
        dir_entries = sorted(os.listdir(abs_path))
    except OSError:
        return result
    
    for name in dir_entries:
        if exclude_names and name in exclude_names:
            continue
        
        full_path = os.path.join(abs_path, name)
        rel_path = full_path  # We store the full path as we don't have a base path
        
        if os.path.isdir(full_path):
            # Add directory
            children = dir_tree(full_path, exclude_names, excluded_extensions, allowed_extensions)
            result.append({
                'name': name,
                'path': rel_path,
                'type': 'directory',
                'children': children
            })
        else:
            # Check file extension
            ext = get_file_extension(name)
            if (
                (excluded_extensions and ext in excluded_extensions) or
                (allowed_extensions and ext not in allowed_extensions)
            ):
                continue
                
            # Add file
            result.append({
                'name': name,
                'path': rel_path,
                'type': 'file'
            })
    
    return result


def read_file(file_path, encoding='utf-8'):
    """Read a file and return its content
    
    Args:
        file_path (str): Path to the file
        encoding (str, optional): File encoding. Defaults to 'utf-8'.
        
    Returns:
        tuple: (success, content or error message)
    """
    try:
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"
        
        if not os.path.isfile(file_path):
            return False, f"Not a file: {file_path}"
        
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        
        return True, content
    except Exception as e:
        return False, f"Error reading file: {str(e)}"