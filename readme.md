# Claude Code Agent - React TypeScript Edition

**Warning!** This agent can execute bash commands, SQL queries, Python code, and modify files on your system. It is strongly recommended to run this inside a VM or Docker container to prevent accidental data loss.

This is a modern React TypeScript rewrite of the original Python Flask application, providing a better user experience with improved performance, type safety, and maintainability.

## Architecture

### Frontend (React TypeScript)
- **Modern React 19** with TypeScript for type safety
- **Vite** for fast development and building
- **Tailwind CSS** for responsive, dark-themed UI
- **Socket.IO Client** for real-time communication
- **React Markdown** with syntax highlighting
- **Comprehensive testing** with Vitest and React Testing Library

### Backend (Python Flask)
- Flask server serving both API endpoints and React build
- Socket.IO for real-time communication
- File upload handling
- Conversation history management

## Quick Start

### Prerequisites

1. **Python 3.8+** and required dependencies
2. **Node.js 18+** and npm
3. **Nix** (optional, for original setup):
   ```sh
   curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
   ```

### Development Setup

1. **Set up the frontend:**
   ```sh
   cd frontend
   npm install
   npm run dev  # Start development server on http://localhost:5173
   ```

2. **Set up the backend:**
   ```sh
   export ANTHROPIC_API_KEY=your-anthropic-key
   python agent.py --port 5000
   ```

### Production Build

1. **Build the React frontend:**
   ```sh
   ./build-frontend.sh
   ```
   Or manually:
   ```sh
   cd frontend
   npm run build
   cd ..
   cp -r frontend/dist frontend-dist
   ```

2. **Run the production server:**
   ```sh
   export ANTHROPIC_API_KEY=your-anthropic-key
   python agent.py --port 5000
   ```
   The React app will be served at http://localhost:5000

### Using Nix (Legacy)

```sh
export ANTHROPIC_API_KEY=your-anthropic-key
nix run github:r33drichards/bash-agent#webagent -- --working-dir `pwd` --port 5556 --metadata-dir `pwd`/meta
```

## Features

### Agent Capabilities
The agent has access to several powerful tools:
1. **Bash Tool**: Execute shell commands
2. **SQLite Tool**: Query and modify SQLite databases  
3. **IPython Tool**: Execute Python code with access to common libraries
4. **File Editing Tools**: Apply diffs and overwrite files
5. **GitHub RAG**: Search and analyze GitHub repositories

### UI Features
- 🌙 **Dark Theme**: GitHub-inspired dark interface
- 💬 **Real-time Chat**: Streaming responses with typing indicators
- 📁 **File Upload**: Drag & drop or paste images and documents
- 🔧 **Tool Confirmations**: Preview and approve tool executions
- 📊 **Token Counter**: Live token usage tracking with animations
- 📜 **Chat History**: Save and load previous conversations
- ⚡ **Auto-confirm**: Toggle for automatic tool approval
- 🎨 **Syntax Highlighting**: Code blocks with proper highlighting
- 📱 **Responsive Design**: Works on desktop and mobile

## Development Commands

### Frontend
```sh
cd frontend
npm run dev          # Start development server
npm run build        # Build for production
npm run lint         # Lint code
npm run lint:fix     # Fix linting issues
npm run format       # Format code with Prettier
npm run type-check   # Check TypeScript types
npm run test         # Run tests
npm run test:ui      # Run tests with UI
```

### Backend
```sh
python agent.py --help     # See all options
python test_agent.py       # Run backend tests
```

## Project Structure

```
.
├── frontend/                 # React TypeScript frontend
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── hooks/           # Custom React hooks
│   │   ├── types/           # TypeScript type definitions
│   │   └── test/            # Test utilities and setup
│   ├── package.json         # Node.js dependencies
│   ├── vite.config.ts       # Vite configuration
│   ├── tailwind.config.js   # Tailwind CSS configuration
│   └── tsconfig.json        # TypeScript configuration
├── frontend-dist/           # Built React app (generated)
├── templates/               # Legacy Flask templates
├── agent.py                 # Main Flask application
├── memory.py               # Memory management
├── todos.py                # Todo management
├── github_rag.py           # GitHub repository analysis
├── build-frontend.sh       # Frontend build script
└── requirements.txt        # Python dependencies
```

## Technology Stack

### Frontend
- **React 19** - Modern React with latest features
- **TypeScript** - Type safety and better DX
- **Vite 5** - Fast build tool and dev server
- **Tailwind CSS 4** - Utility-first CSS framework
- **Socket.IO Client** - Real-time communication
- **React Markdown** - Markdown rendering with syntax highlighting
- **Lucide React** - Beautiful icons
- **Vitest** - Fast unit testing
- **React Testing Library** - Component testing utilities

### Backend
- **Flask** - Python web framework
- **Socket.IO** - Real-time bidirectional communication
- **Anthropic Claude** - AI language model
- **SQLite** - Embedded database
- **IPython** - Interactive Python shell

## Security Warning

This agent can:
- Execute arbitrary bash commands
- Run SQL queries on any SQLite database
- Execute Python code
- Modify or overwrite any file on your system

**Use with caution and preferably in an isolated environment like Docker or a VM.**