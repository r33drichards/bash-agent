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

def main():
    parser = argparse.ArgumentParser(description='LLM Agent Web Server')
    parser.add_argument('--prompt-file', type=str, default=None, required=False,
                      help='Path to the prompt file (default: prompt.md)')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the server on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to run the server on')
    parser.add_argument('--auto-confirm', action='store_true', help='Automatically confirm all actions without prompting')
    args = parser.parse_args()
    
    # Store global config
    app.config['PROMPT_FILE'] = args.prompt_file
    app.config['AUTO_CONFIRM'] = args.auto_confirm
    
    print(f"\n=== LLM Agent Web Server ===")
    print(f"Starting server on http://{args.host}:{args.port}")
    print("Claude Code-like interface available in your browser")
    
    socketio.run(app, host=args.host, port=args.port, debug=True, allow_unsafe_werkzeug=True)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    session_id = str(uuid.uuid4())
    join_room(session_id)
    session['session_id'] = session_id
    
    # Initialize session with LLM
    sessions[session_id] = {
        'llm': LLM("claude-3-7-sonnet-latest", app.config['PROMPT_FILE']),
        'auto_confirm': app.config['AUTO_CONFIRM'],
        'connected_at': datetime.now()
    }
    
    emit('session_started', {'session_id': session_id})
    emit('message', {
        'type': 'system',
        'content': 'Connected to Claude Code Agent. Type your message to start...',
        'timestamp': datetime.now().isoformat()
    })

@socketio.on('disconnect')
def handle_disconnect():
    session_id = session.get('session_id')
    if session_id in sessions:
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
    emit('message', {
        'type': 'user',
        'content': user_input,
        'timestamp': datetime.now().isoformat()
    })
    
    # Process with LLM
    try:
        llm = sessions[session_id]['llm']
        auto_confirm = sessions[session_id]['auto_confirm']
        
        msg = [{"type": "text", "text": user_input}]
        output, tool_calls = llm(msg)
        
        # Send agent response
        emit('message', {
            'type': 'agent',
            'content': output,
            'timestamp': datetime.now().isoformat()
        })
        
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
        # Send cancellation message
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
        if result and 'content' in result and result['content']:
            result_content = result['content'][0]['text'] if result['content'][0]['type'] == 'text' else str(result['content'])
        
        # Send detailed execution result
        emit('tool_execution_result', {
            'type': 'tool_result',
            'tool_name': tool_call['name'],
            'result': result_content,
            'timestamp': datetime.now().isoformat()
        }, room=session_id)
        
        # Send result back to LLM
        llm = sessions[session_id]['llm']
        output, new_tool_calls = llm([result])
        
        # Send agent response
        emit('message', {
            'type': 'agent',
            'content': output,
            'timestamp': datetime.now().isoformat()
        }, room=session_id)
        
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
        output_text = execute_ipython(code, print_result)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
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
    shell = InteractiveShell.instance()
    output_buffer = io.StringIO()
    error_buffer = io.StringIO()
    rich_output = ""
    try:
        with capture_output() as cap:
            with contextlib.redirect_stdout(output_buffer):
                with contextlib.redirect_stderr(error_buffer):
                    result = shell.run_cell(code, store_history=False)
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
        output_text = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}\nRICH OUTPUT:\n{rich_output}"
        if print_result:
            print(f"IPython output:\n{output_text}")
        return output_text
    except Exception as e:
        return f"Error executing Python code: {str(e)}"

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