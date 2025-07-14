#!/usr/bin/env python3
"""
GitHub Auth Tool - A tool to clone GitHub repositories with device authentication
"""

import os
import sys
import subprocess
import json
from typing import Dict, Any, Optional, Tuple

# Import the GitHub authentication module
from github_auth import GitHubAuth

def execute_github_clone(repo_url: str, target_dir: str = None, shallow: bool = True):
    """
    Clone a GitHub repository with device authentication.
    
    Args:
        repo_url: URL of the GitHub repository to clone
        target_dir: Directory to clone into (default: current directory)
        shallow: Whether to do a shallow clone (default: True)
        
    Returns:
        Output text with clone results
    """
    try:
        # Use current directory if no target specified
        if not target_dir:
            target_dir = os.getcwd()
            
        # Create target directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)
        
        # Get the repository name from the URL
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        repo_path = os.path.join(target_dir, repo_name)
        
        # Build the git clone command
        clone_cmd = ['git', 'clone']
        if shallow:
            clone_cmd.extend(['--depth', '1'])
        clone_cmd.extend([repo_url, repo_path])
        
        # First try to clone without authentication (for public repos)
        print(f"Attempting to clone {repo_url} to {repo_path}...")
        result = subprocess.run(clone_cmd, capture_output=True, text=True)
        
        # Check if the command was successful
        if result.returncode != 0:
            print("Public clone failed, trying with authentication...")
            # Try with GitHub authentication if public clone fails
            auth = GitHubAuth()
            success, message = auth.authenticate()
            if success:
                success, message, repo_path = auth.clone_repository(repo_url, target_dir, shallow)
            else:
                return f"Failed to clone repository: {result.stderr}\nGitHub authentication also failed: {message}"
        else:
            success, message = True, f"Repository cloned successfully to {repo_path}"
        
        if success:
            return f"Successfully cloned repository to {repo_path}"
        else:
            return f"Failed to clone repository: {message}"
            
    except Exception as e:
        return f"Error cloning repository: {str(e)}"

# Define the tool schema
github_clone_tool = {
    "name": "github_clone",
    "description": "Clone a GitHub repository using device authentication. If not authenticated, this will initiate a device code flow that requires you to authorize the app on GitHub.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": "URL of the GitHub repository to clone (e.g., https://github.com/username/repo)"
            },
            "target_dir": {
                "type": "string",
                "description": "Directory to clone the repository into (default: current directory)"
            },
            "shallow": {
                "type": "boolean",
                "description": "Whether to do a shallow clone (default: true)"
            }
        },
        "required": ["repo_url"]
    }
}

if __name__ == "__main__":
    # Simple test
    if len(sys.argv) > 1:
        result = execute_github_clone(sys.argv[1])
        print(result)
    else:
        print("Usage: python github_auth_tool.py <repo_url>")