import os
import subprocess
import argparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import uuid
import threading
from datetime import datetime
import time
import signal
import tempfile
import psutil

import anthropic
from anthropic import RateLimitError, APIError
import sqlite3
import json
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output
import io
import contextlib

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room

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
    """API endpoint to handle file uploads"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    try:
        # Save the file to the current working directory
        filename = file.filename
        file_path = os.path.join(os.getcwd(), filename)
        
        # Check if file already exists and create a unique name if needed
        counter = 1
        base_name, ext = os.path.splitext(filename)
        while os.path.exists(file_path):
            filename = f"{base_name}_{counter}{ext}"
            file_path = os.path.join(os.getcwd(), filename)
            counter += 1
        
        file.save(file_path)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'path': file_path
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    session_id = str(uuid.uuid4())
    join_room(session_id)
    session['session_id'] = session_id
    
    # Initialize session with LLM
    sessions[session_id] = {
        'llm': LLM("claude-3-7-sonnet-latest"),
        'auto_confirm': app.config['AUTO_CONFIRM'],
        'connected_at': datetime.now(),
        'conversation_history': [],
        'background_tasks': {}
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
        # Clean up background tasks before session cleanup
        cleanup_background_tasks(session_id)
        # Save conversation history before cleanup
        save_conversation_history(session_id)
        del sessions[session_id]
    leave_room(session_id)

@socketio.on('user_message')
def handle_user_message(data):
    session_id = session.get('session_id')
    if session_id not in sessions:
        emit('error', {'message': 'Session not found'})
        return
    
    user_input = data.get('message', '').strip()
    if not user_input:
        return
    
    # Echo user message
    user_message = {
        'type': 'user',
        'content': user_input,
        'timestamp': datetime.now().isoformat()
    }
    emit('message', user_message)
    
    # Store in conversation history
    sessions[session_id]['conversation_history'].append(user_message)
    
    # Process with LLM
    try:
        llm = sessions[session_id]['llm']
        auto_confirm = sessions[session_id]['auto_confirm']
        
        msg = [{"type": "text", "text": user_input}]
        output, tool_calls = llm(msg)
        
        # Send agent response
        agent_message = {
            'type': 'agent',
            'content': output,
            'timestamp': datetime.now().isoformat()
        }
        emit('message', agent_message)
        
        # Store in conversation history
        sessions[session_id]['conversation_history'].append(agent_message)
        
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
        output_text = execute_bash(command)
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
    elif tool_call["name"] == "create_bg_task":
        command = tool_call["input"]["command"]
        name = tool_call["input"]["name"]
        working_dir = tool_call["input"].get("working_dir", None)
        output_text = create_background_task(command, name, working_dir)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "list_bg_tasks":
        output_text = list_background_tasks()
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "kill_bg_task":
        task_id = tool_call["input"]["task_id"]
        output_text = kill_background_task(task_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "logs_bg_task":
        task_id = tool_call["input"]["task_id"]
        lines = tool_call["input"].get("lines", 50)
        output_text = get_background_task_logs(task_id, lines)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "restart_bg_task":
        task_id = tool_call["input"]["task_id"]
        output_text = restart_background_task(task_id)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    else:
        raise Exception(f"Unsupported tool: {tool_call['name']}")


bash_tool = {
    "name": "bash",
    "description": "Execute bash commands and return the output",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute"
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

# --- Background Task tools ---
create_bg_task_tool = {
    "name": "create_bg_task",
    "description": "Start a non-blocking background shell command that runs continuously. Perfect for starting web servers, daemons, or long-running processes. Returns a task ID for management.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run in the background."
            },
            "name": {
                "type": "string",
                "description": "A descriptive name for the background task."
            },
            "working_dir": {
                "type": "string",
                "description": "Optional working directory for the command."
            }
        },
        "required": ["command", "name"]
    }
}

list_bg_tasks_tool = {
    "name": "list_bg_tasks",
    "description": "List all background tasks for the current session with their status, PIDs, and runtime information.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

kill_bg_task_tool = {
    "name": "kill_bg_task", 
    "description": "Stop a running background task by task ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the background task to stop."
            }
        },
        "required": ["task_id"]
    }
}

logs_bg_task_tool = {
    "name": "logs_bg_task",
    "description": "Get the output logs from a background task. Shows recent stdout, stderr, and status information.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string", 
                "description": "The ID of the background task to get logs for."
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent log lines to show (default: 50)."
            }
        },
        "required": ["task_id"]
    }
}

restart_bg_task_tool = {
    "name": "restart_bg_task",
    "description": "Restart a background task by stopping it if running and starting it again with the same configuration.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the background task to restart."
            }
        },
        "required": ["task_id"]
    }
}

# Global dictionary to store background tasks across all sessions
background_tasks = {}

def get_current_session_id():
    """Get the current session ID from Flask session context"""
    from flask import session as flask_session
    return flask_session.get('session_id')

def create_background_task(command, name, working_dir=None):
    """Create and start a background task"""
    session_id = get_current_session_id()
    if not session_id or session_id not in sessions:
        return "Error: No active session found"
    
    task_id = str(uuid.uuid4())[:8]
    
    try:
        # Create temporary files for stdout and stderr
        stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix=f'bg_task_{task_id}_stdout_')
        stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix=f'bg_task_{task_id}_stderr_')
        
        # Start the process
        cwd = working_dir if working_dir and os.path.exists(working_dir) else os.getcwd()
        
        process = subprocess.Popen(
            ["bash", "-c", command],
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=cwd,
            preexec_fn=os.setsid  # Create new process group for clean termination
        )
        
        # Store task information
        task_info = {
            'id': task_id,
            'name': name,
            'command': command,
            'working_dir': cwd,
            'process': process,
            'pid': process.pid,
            'started_at': datetime.now(),
            'session_id': session_id,
            'stdout_file': stdout_file.name,
            'stderr_file': stderr_file.name,
            'status': 'running'
        }
        
        background_tasks[task_id] = task_info
        sessions[session_id]['background_tasks'][task_id] = task_info
        
        # Close file handles but keep files for logging
        stdout_file.close()
        stderr_file.close()
        
        return f"Background task '{name}' started successfully!\nTask ID: {task_id}\nPID: {process.pid}\nCommand: {command}\nWorking directory: {cwd}"
        
    except Exception as e:
        return f"Error starting background task: {str(e)}"

def list_background_tasks():
    """List all background tasks for the current session"""
    session_id = get_current_session_id()
    if not session_id or session_id not in sessions:
        return "Error: No active session found"
    
    session_tasks = sessions[session_id]['background_tasks']
    
    if not session_tasks:
        return "No background tasks running in this session."
    
    output_lines = ["Background Tasks:", "=" * 50]
    
    for task_id, task in session_tasks.items():
        # Update task status
        _update_task_status(task)
        
        runtime = datetime.now() - task['started_at']
        runtime_str = str(runtime).split('.')[0]  # Remove microseconds
        
        output_lines.append(f"Task ID: {task_id}")
        output_lines.append(f"  Name: {task['name']}")
        output_lines.append(f"  Command: {task['command']}")
        output_lines.append(f"  Status: {task['status']}")
        output_lines.append(f"  PID: {task['pid']}")
        output_lines.append(f"  Runtime: {runtime_str}")
        output_lines.append(f"  Working Dir: {task['working_dir']}")
        output_lines.append("")
    
    return "\n".join(output_lines)

def kill_background_task(task_id):
    """Stop a background task"""
    session_id = get_current_session_id()
    if not session_id or session_id not in sessions:
        return "Error: No active session found"
    
    if task_id not in sessions[session_id]['background_tasks']:
        return f"Error: Task {task_id} not found in current session"
    
    task = sessions[session_id]['background_tasks'][task_id]
    
    try:
        if task['status'] == 'running':
            # Try to terminate the process group gracefully
            try:
                os.killpg(os.getpgid(task['pid']), signal.SIGTERM)
                time.sleep(1)  # Give it a moment to terminate gracefully
                
                # Check if still running and force kill if needed
                if task['process'].poll() is None:
                    os.killpg(os.getpgid(task['pid']), signal.SIGKILL)
                    
            except ProcessLookupError:
                pass  # Process already terminated
            except Exception as e:
                return f"Error terminating task {task_id}: {str(e)}"
        
        # Update task status
        _update_task_status(task)
        task['status'] = 'stopped'
        task['stopped_at'] = datetime.now()
        
        return f"Background task '{task['name']}' (ID: {task_id}) has been stopped."
        
    except Exception as e:
        return f"Error stopping background task: {str(e)}"

def get_background_task_logs(task_id, lines=50):
    """Get logs from a background task"""
    session_id = get_current_session_id()
    if not session_id or session_id not in sessions:
        return "Error: No active session found"
    
    if task_id not in sessions[session_id]['background_tasks']:
        return f"Error: Task {task_id} not found in current session"
    
    task = sessions[session_id]['background_tasks'][task_id]
    
    try:
        # Update task status
        _update_task_status(task)
        
        # Read stdout
        stdout_content = ""
        if os.path.exists(task['stdout_file']):
            with open(task['stdout_file'], 'r') as f:
                stdout_lines = f.readlines()
                if len(stdout_lines) > lines:
                    stdout_lines = stdout_lines[-lines:]
                stdout_content = ''.join(stdout_lines)
        
        # Read stderr  
        stderr_content = ""
        if os.path.exists(task['stderr_file']):
            with open(task['stderr_file'], 'r') as f:
                stderr_lines = f.readlines()
                if len(stderr_lines) > lines:
                    stderr_lines = stderr_lines[-lines:]
                stderr_content = ''.join(stderr_lines)
        
        runtime = datetime.now() - task['started_at']
        runtime_str = str(runtime).split('.')[0]
        
        output = f"Logs for Background Task: {task['name']} (ID: {task_id})\n"
        output += f"Status: {task['status']}\n"
        output += f"PID: {task['pid']}\n"
        output += f"Runtime: {runtime_str}\n"
        output += f"Command: {task['command']}\n"
        output += "=" * 60 + "\n"
        
        if stdout_content:
            output += f"STDOUT (last {lines} lines):\n{stdout_content}\n"
        else:
            output += "STDOUT: (empty)\n"
            
        if stderr_content:
            output += f"STDERR (last {lines} lines):\n{stderr_content}\n"
        else:
            output += "STDERR: (empty)\n"
        
        return output
        
    except Exception as e:
        return f"Error reading task logs: {str(e)}"

def restart_background_task(task_id):
    """Restart a background task by stopping it and starting it again"""
    session_id = get_current_session_id()
    if not session_id or session_id not in sessions:
        return "Error: No active session found"
    
    if task_id not in sessions[session_id]['background_tasks']:
        return f"Error: Task {task_id} not found in current session"
    
    task = sessions[session_id]['background_tasks'][task_id]
    
    try:
        # Store original task configuration
        original_command = task['command']
        original_name = task['name']
        original_working_dir = task['working_dir']
        
        # Stop the task if it's running
        if task['status'] == 'running':
            try:
                # Try to terminate the process group gracefully
                os.killpg(os.getpgid(task['pid']), signal.SIGTERM)
                time.sleep(1)  # Give it a moment to terminate gracefully
                
                # Check if still running and force kill if needed
                if task['process'].poll() is None:
                    os.killpg(os.getpgid(task['pid']), signal.SIGKILL)
                    
            except ProcessLookupError:
                pass  # Process already terminated
            except Exception as e:
                return f"Error stopping task {task_id} for restart: {str(e)}"
        
        # Clean up old log files
        try:
            for file_path in [task['stdout_file'], task['stderr_file']]:
                if os.path.exists(file_path):
                    os.unlink(file_path)
        except Exception:
            pass  # Continue even if cleanup fails
        
        # Create new temporary files for stdout and stderr
        stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix=f'bg_task_{task_id}_stdout_')
        stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix=f'bg_task_{task_id}_stderr_')
        
        # Start new process
        cwd = original_working_dir if original_working_dir and os.path.exists(original_working_dir) else os.getcwd()
        
        process = subprocess.Popen(
            ["bash", "-c", original_command],
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=cwd,
            preexec_fn=os.setsid  # Create new process group for clean termination
        )
        
        # Update task information with new process
        task.update({
            'process': process,
            'pid': process.pid,
            'started_at': datetime.now(),
            'stdout_file': stdout_file.name,
            'stderr_file': stderr_file.name,
            'status': 'running'
        })
        
        # Remove old timestamps
        if 'stopped_at' in task:
            del task['stopped_at']
        if 'exit_code' in task:
            del task['exit_code']
        
        # Close file handles but keep files for logging
        stdout_file.close()
        stderr_file.close()
        
        return f"Background task '{original_name}' (ID: {task_id}) restarted successfully!\nNew PID: {process.pid}\nCommand: {original_command}\nWorking directory: {cwd}"
        
    except Exception as e:
        return f"Error restarting background task: {str(e)}"

def _update_task_status(task):
    """Update the status of a background task"""
    try:
        if task['process'].poll() is None:
            # Process is still running
            task['status'] = 'running'
        else:
            # Process has finished
            task['status'] = 'completed' if task['process'].returncode == 0 else 'failed'
            task['exit_code'] = task['process'].returncode
            if 'stopped_at' not in task:
                task['stopped_at'] = datetime.now()
    except Exception:
        task['status'] = 'unknown'

def cleanup_background_tasks(session_id):
    """Clean up background tasks when a session ends"""
    if session_id not in sessions:
        return
        
    session_tasks = sessions[session_id]['background_tasks']
    
    for task_id, task in session_tasks.items():
        try:
            # Stop running processes
            if task['status'] == 'running' and task['process'].poll() is None:
                os.killpg(os.getpgid(task['pid']), signal.SIGTERM)
                time.sleep(0.5)
                if task['process'].poll() is None:
                    os.killpg(os.getpgid(task['pid']), signal.SIGKILL)
            
            # Clean up log files
            for file_path in [task['stdout_file'], task['stderr_file']]:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    
        except Exception as e:
            print(f"Error cleaning up background task {task_id}: {e}")
    
    # Remove from global tasks
    for task_id in list(session_tasks.keys()):
        if task_id in background_tasks:
            del background_tasks[task_id]

def execute_bash(command):
    """Execute a bash command and return a formatted string with the results."""
    # If we have a timeout exception, we'll return an error message instead
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=30
        )
        # encode output so that text doesn't contain [32m      4[39m [38;5;66;03m# Calculate profit metrics[39;00m
        result.stdout = result.stdout.encode('utf-8').decode('utf-8')
        result.stderr = result.stderr.encode('utf-8').decode('utf-8')
        
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nEXIT CODE: {result.returncode}"
    except Exception as e:
        return f"Error executing command: {str(e)}"

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


class LLM:
    def __init__(self, model):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise ValueError("ANTHROPIC_API_KEY environment variable not found.")
        self.client = anthropic.Anthropic()
        self.model = model
        self.messages = []
        self.system_prompt = (
            """You are a helpful AI assistant with access to bash, sqlite, Python, and file editing tools.\n"""
            "You can help the user by executing commands and interpreting the results.\n"
            "Be careful with destructive commands and always explain what you're doing.\n\n"
            
            "AVAILABLE TOOLS:\n"
            "- bash: Run shell commands\n"
            "- sqlite: Execute SQL queries on SQLite databases\n"
            "- ipython: Execute Python code with rich output support\n"
            "- edit_file_diff: Apply unified diff patches to files\n"
            "- overwrite_file: Replace entire file contents\n"
            "- Background task tools: create_bg_task, list_bg_tasks, kill_bg_task, logs_bg_task, restart_bg_task\n\n"
            
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
            + (app.config['SYSTEM_PROMPT'] if 'SYSTEM_PROMPT' in app.config and app.config['SYSTEM_PROMPT'] else "")
        )
        self.tools = [bash_tool, sqlite_tool, ipython_tool, edit_file_diff_tool, overwrite_file_tool, create_bg_task_tool, list_bg_tasks_tool, kill_bg_task_tool, logs_bg_task_tool, restart_bg_task_tool]

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True
    )
    def _call_anthropic(self):
        return self.client.messages.create(
            model=self.model,
            max_tokens=20_000,
            system=self.system_prompt,
            messages=self.messages,
            tools=self.tools
        )

    def __call__(self, content):
        self.messages.append({"role": "user", "content": content})
        self.messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        try:
            response = self._call_anthropic()
        except (RateLimitError, APIError) as e:
            print(f"\nRate limit or API error occurred: {str(e)}")
            raise
        finally:
            del self.messages[-1]["content"][-1]["cache_control"]
        assistant_response = {"role": "assistant", "content": []}
        tool_calls = []
        output_text = ""

        for content in response.content:
            if content.type == "text":
                text_content = content.text
                output_text += text_content
                assistant_response["content"].append({"type": "text", "text": text_content})
            elif content.type == "tool_use":
                assistant_response["content"].append(content)
                tool_calls.append({
                    "id": content.id,
                    "name": content.name,
                    "input": content.input
                })

        self.messages.append(assistant_response)
        return output_text, tool_calls


if __name__ == "__main__":
    main()