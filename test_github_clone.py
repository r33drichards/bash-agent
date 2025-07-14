#!/usr/bin/env python3
import os
import tempfile
from github_auth_tool import execute_github_clone

if __name__ == "__main__":
    # Create a temporary directory for the cloned repository
    tmp_dir = tempfile.mkdtemp()
    # Test cloning a small repository
    result = execute_github_clone(
        repo_url="https://github.com/octocat/Hello-World.git",
        target_dir=tmp_dir,
        shallow=True
    )
    print(result)
    print(f"Working directory: {tmp_dir}")
