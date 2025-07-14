# Monaco Editor for bash-agent

This feature adds a Monaco code editor tab to the bash-agent web interface, allowing you to easily edit files in the container.

## Features

- **Monaco Editor Integration**: Professional code editor with syntax highlighting for many languages
- **File Browser**: View and select files in the current directory
- **File Operations**:
  - View files with proper syntax highlighting
  - Edit files with real-time changes
  - Save changes back to the filesystem
  - Create new files

## Usage

1. Start the bash-agent server:
   ```bash
   python agent.py
   ```

2. Access the Monaco editor by clicking the "Monaco Editor" button in the top right of the main chat interface, or directly navigating to `/monaco`

3. Use the file browser on the left to select files to edit

4. Edit files in the Monaco editor

5. Click "Save" to save changes back to the filesystem

## Implementation Details

The Monaco editor feature is implemented with the following components:

1. **Monaco Editor UI**: A dedicated web page (`monaco.html`) that provides the editor interface
2. **API Endpoints**: Backend routes to support file listing, reading, and writing
3. **Integration**: Seamless integration with the bash-agent web interface

### Files

- `monaco.html`: The main Monaco editor interface
- `monaco_routes.py`: Flask routes to handle file operations
- Integration in `agent.py`: Registration of the Monaco Blueprint

### API Endpoints

- `GET /api/monaco/files`: List files in the current directory
- `GET /api/monaco/file?path=<path>`: Get content of a specific file
- `POST /api/monaco/save`: Save file content to the filesystem

## Future Improvements

Potential future enhancements:
- Recursive file browser with folder support
- Search functionality
- Multiple file tabs
- Git integration
- More advanced file operations (rename, delete, etc.)