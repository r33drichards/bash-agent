#!/usr/bin/env python3
"""
GitHub Authentication - Device code flow authentication for GitHub
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class GitHubAuth:
    """GitHub authentication using device code flow."""
    
    def __init__(self, client_id: str = "01ab8ac15feee507b7a5"):
        """
        Initialize GitHub authentication.
        
        Args:
            client_id: GitHub OAuth client ID (default: public client ID for CLI apps)
        """
        self.client_id = client_id
        self.token_file = os.path.expanduser("~/.github_token.json")
        self._token_data = None
    
    def _load_token(self) -> Optional[Dict[str, Any]]:
        """Load GitHub token from file if it exists."""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
                    
                # Check if token is expired
                if 'expires_at' in token_data:
                    expires_at = datetime.fromisoformat(token_data['expires_at'])
                    if expires_at > datetime.now():
                        return token_data
            except Exception as e:
                logger.warning(f"Error loading GitHub token: {e}")
        
        return None
    
    def _save_token(self, token_data: Dict[str, Any]) -> None:
        """Save GitHub token to file."""
        # Add expiration time (default to 8 hours from now if not provided)
        if 'expires_in' in token_data:
            token_data['expires_at'] = (datetime.now() + timedelta(seconds=token_data['expires_in'])).isoformat()
        else:
            token_data['expires_at'] = (datetime.now() + timedelta(hours=8)).isoformat()
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.expanduser(self.token_file)), exist_ok=True)
            
            # Save token with restricted permissions
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f)
            
            # Set permissions to owner read/write only
            os.chmod(self.token_file, 0o600)
        except Exception as e:
            logger.error(f"Error saving GitHub token: {e}")
    
    def get_token(self) -> Optional[str]:
        """
        Get a valid GitHub token, refreshing if necessary.
        
        Returns:
            GitHub access token or None if unable to authenticate
        """
        # Check for cached token
        if self._token_data and 'expires_at' in self._token_data:
            expires_at = datetime.fromisoformat(self._token_data['expires_at'])
            if expires_at > datetime.now():
                return self._token_data.get('access_token')
        
        # Try to load token from file
        token_data = self._load_token()
        if token_data and 'access_token' in token_data:
            self._token_data = token_data
            return token_data['access_token']
        
        return None
    
    def initiate_device_flow(self) -> Dict[str, Any]:
        """
        Initiate the device code flow.
        
        Returns:
            Dictionary with device_code, user_code, verification_uri, etc.
        """
        response = requests.post(
            'https://github.com/login/device/code',
            data={
                'client_id': self.client_id,
                'scope': 'repo'  # Access to repositories
            },
            headers={
                'Accept': 'application/json'
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to initiate device flow: {response.text}")
        
        device_data = response.json()
        return device_data
    
    def poll_for_token(self, device_code: str, interval: int = 5, max_attempts: int = 60) -> Optional[Dict[str, Any]]:
        """
        Poll for the token after user authorization.
        
        Args:
            device_code: Device code from initiate_device_flow
            interval: Polling interval in seconds
            max_attempts: Maximum number of polling attempts
        
        Returns:
            Token data dictionary or None if authentication failed or timed out
        """
        for _ in range(max_attempts):
            try:
                response = requests.post(
                    'https://github.com/login/oauth/access_token',
                    data={
                        'client_id': self.client_id,
                        'device_code': device_code,
                        'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
                    },
                    headers={
                        'Accept': 'application/json'
                    }
                )
                
                data = response.json()
                
                # Check for errors
                if 'error' in data:
                    # authorization_pending means the user hasn't completed auth yet
                    if data['error'] == 'authorization_pending':
                        time.sleep(interval)
                        continue
                    elif data['error'] == 'slow_down':
                        # GitHub is asking us to slow down polling
                        interval += 1
                        time.sleep(interval)
                        continue
                    else:
                        # Other errors are terminal
                        raise Exception(f"Authentication error: {data['error']}")
                
                # Success - we have a token
                if 'access_token' in data:
                    self._token_data = data
                    self._save_token(data)
                    return data
            
            except Exception as e:
                logger.error(f"Error polling for token: {e}")
                time.sleep(interval)
        
        return None
    
    def authenticate(self, print_callback=None) -> Tuple[bool, Optional[str]]:
        """
        Authenticate with GitHub using device code flow.
        
        Args:
            print_callback: Optional callback function to print messages to the user
            
        Returns:
            Tuple of (success, message)
        """
        # Check for existing token
        token = self.get_token()
        if token:
            return True, "Using existing GitHub authentication"
        
        try:
            # Start device flow
            device_data = self.initiate_device_flow()
            
            user_code = device_data.get('user_code')
            verification_uri = device_data.get('verification_uri')
            
            message = (
                f"To authenticate with GitHub, please visit:\n\n"
                f"{verification_uri}\n\n"
                f"And enter code: {user_code}\n\n"
                f"Waiting for authentication..."
            )
            
            if print_callback:
                print_callback(message)
            else:
                print(message)
            
            # Poll for token
            token_data = self.poll_for_token(
                device_data.get('device_code'),
                interval=device_data.get('interval', 5),
                max_attempts=120  # Allow up to 10 minutes
            )
            
            if not token_data or 'access_token' not in token_data:
                return False, "Authentication failed or timed out"
            
            success_message = "Successfully authenticated with GitHub!"
            if print_callback:
                print_callback(success_message)
            else:
                print(success_message)
            
            return True, success_message
            
        except Exception as e:
            error_message = f"Error during GitHub authentication: {str(e)}"
            if print_callback:
                print_callback(error_message)
            else:
                print(error_message)
            
            return False, error_message
    
    def clone_repository(self, repo_url: str, target_dir: str, shallow: bool = True) -> Tuple[bool, str, Optional[str]]:
        """
        Clone a GitHub repository using authentication.
        
        Args:
            repo_url: GitHub repository URL
            target_dir: Directory to clone into
            shallow: Whether to do a shallow clone
            
        Returns:
            Tuple of (success, message, repo_path)
        """
        try:
            # Get authentication token
            token = self.get_token()
            
            # Parse the URL to add token
            if token and 'github.com' in repo_url:
                # Convert HTTPS URL to use token
                if repo_url.startswith('https://'):
                    repo_url = repo_url.replace('https://', f'https://oauth2:{token}@')
                # For SSH URLs, we'll continue to use the original URL
            
            # Create target directory
            os.makedirs(target_dir, exist_ok=True)
            
            # Generate repo path
            repo_name = repo_url.split('/')[-1].replace('.git', '')
            repo_path = os.path.join(target_dir, repo_name)
            
            # Build clone command
            import subprocess
            clone_cmd = ['git', 'clone']
            if shallow:
                clone_cmd.extend(['--depth', '1'])
            clone_cmd.extend([repo_url, repo_path])
            
            # Clone repository
            result = subprocess.run(clone_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                return False, f"Error cloning repository: {result.stderr}", None
            
            return True, f"Repository cloned successfully to {repo_path}", repo_path
            
        except Exception as e:
            return False, f"Error cloning repository: {str(e)}", None
    
    def logout(self) -> Tuple[bool, str]:
        """
        Remove GitHub authentication token.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
            
            self._token_data = None
            return True, "Successfully logged out from GitHub"
        except Exception as e:
            return False, f"Error logging out: {str(e)}"


if __name__ == "__main__":
    # Example usage
    auth = GitHubAuth()
    success, message = auth.authenticate()
    
    if success:
        print("Token:", auth.get_token())
        
        # Example clone
        success, message, repo_path = auth.clone_repository(
            "https://github.com/octocat/Hello-World",
            "/tmp"
        )
        print(message)
    else:
        print("Authentication failed:", message)