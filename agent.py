import os
import subprocess
import argparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import uuid
import threading
from datetime import datetime

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
    parser.add_argument('--prompt-file', type=str, default=None, required=False,
                      help='Path to the prompt file (default: prompt.md)')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the server on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to run the server on')
    parser.add_argument('--auto-confirm', action='store_true', help='Automatically confirm all actions without prompting')
    parser.add_argument('--working-dir', type=str, default=None, help='Set the working directory for tool execution')
    parser.add_argument('--metadata-dir', type=str, default=None, help='Directory to store conversation history and metadata')
    args = parser.parse_args()
    
    # Store global config
    app.config['PROMPT_FILE'] = args.prompt_file
    app.config['AUTO_CONFIRM'] = args.auto_confirm
    app.config['WORKING_DIR'] = args.working_dir
    app.config['METADATA_DIR'] = args.metadata_dir
    
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

@socketio.on('connect')
def handle_connect():
    session_id = str(uuid.uuid4())
    join_room(session_id)
    session['session_id'] = session_id
    
    # Initialize session with LLM
    sessions[session_id] = {
        'llm': LLM("claude-3-7-sonnet-latest", app.config['PROMPT_FILE']),
        'auto_confirm': app.config['AUTO_CONFIRM'],
        'connected_at': datetime.now(),
        'conversation_history': []
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
# Requires: pip install patch
edit_file_diff_tool = {
    "name": "edit_file_diff",
    "description": "Edit a file by applying a unified diff patch. The input should include the file path and the diff string in unified diff format.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit."
            },
            "diff": {
                "type": "string",
                "description": "Unified diff string to apply to the file."
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
    """Apply a unified diff to a file using the python-patch library. Returns a result string."""
    import tempfile
    import os
    try:
        import patch
    except ImportError:
        return "Error: python-patch library not available. Please install it with: pip install patch"
    
    try:
        # Write the diff to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8', suffix='.patch') as tmp_patch:
            tmp_patch.write(diff)
            patch_path = tmp_patch.name
        # Apply the patch
        pset = patch.fromfile(patch_path)
        if not pset:
            os.unlink(patch_path)
            return "Failed to parse patch file."
        result = pset.apply()
        os.unlink(patch_path)
        if result:
            return f"Applied diff to {file_path}."
        else:
            return f"Failed to apply diff to {file_path}."
    except Exception as e:
        return f"Error applying diff: {str(e)}"

def overwrite_file(file_path, content):
    """Overwrite a file with new content."""
    try:
        with open(file_path, 'w') as f:
            f.write(content)
        return f"Overwrote {file_path} with new content."
    except Exception as e:
        return f"Error overwriting file: {str(e)}"


class LLM:
    def __init__(self, model, prompt_file):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise ValueError("ANTHROPIC_API_KEY environment variable not found.")
        self.client = anthropic.Anthropic()
        self.model = model
        self.messages = []
        if prompt_file:
            # read prompt file from provided path
            with open(prompt_file, 'r') as f:
                prompt = f.read()
        else:
            prompt = ""
        self.system_prompt = (
            """You are a helpful AI assistant with access to bash and sqlite tools.\n"""
            "You can help the user by executing commands and interpreting the results.\n"
            "Be careful with destructive commands and always explain what you're doing.\n"
            "You have access to the bash tool which allows you to run shell commands, and the sqlite tool which allows you to run SQL queries on SQLite databases.\n"
            "For large SELECT queries, you can specify an 'output_json' file path in the sqlite tool input. If you do, write the full result to that file and only print errors or the first record in the response.\n"
            "You can also set 'print_result' to true to print the results in the context window, even if output_json is specified. This is useful for letting you see and reason about the data in context.\n"
            "When generating plots in Python (e.g., with matplotlib), always save the plot to a file (such as .png) and mention the filename in your response. Do not attempt to display plots inline.\n\n"
            "The Python environment for the ipython tool includes: numpy, matplotlib, scikit-learn, ipykernel, torch, tqdm, gymnasium, torchvision, tensorboard, torch-tb-profiler, opencv-python, nbconvert, anthropic, seaborn, pandas, tenacity.\n\n"
            + prompt
        )
        self.tools = [bash_tool, sqlite_tool, ipython_tool, edit_file_diff_tool, overwrite_file_tool]

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