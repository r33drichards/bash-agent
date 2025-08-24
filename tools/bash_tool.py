import subprocess
import time
import select
import os
import fcntl
from datetime import datetime

bash_tool = {
    "name": "bash",
    "description": "Execute bash commands and return the output. Supports custom timeouts and real-time streaming for long-running commands.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30, max: 3600 for 1 hour)"
            },
            "stream_output": {
                "type": "boolean",
                "description": "Stream output in real-time for long-running commands (default: false)"
            }
        },
        "required": ["command"]
    }
}

def execute_bash(command, timeout=30, stream_output=False):
    """Execute a bash command and return a formatted string with the results."""
    # Limit timeout to reasonable maximum
    timeout = min(max(timeout, 1), 3600)  # Between 1 second and 1 hour
    
    try:
        if stream_output:
            return execute_bash_streaming(command, timeout)
        else:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout
            )
        # encode output so that text doesn't contain [32m      4[39m [38;5;66;03m# Calculate profit metrics[39;00m
        result.stdout = result.stdout.encode('utf-8').decode('utf-8')
        result.stderr = result.stderr.encode('utf-8').decode('utf-8')
        
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nEXIT CODE: {result.returncode}"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {str(e)}"

def execute_bash_streaming(command, timeout=30):
    """Execute bash command with real-time output streaming."""
    try:
        # Start the process
        process = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Make stdout and stderr non-blocking
        def make_non_blocking(fd):
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        make_non_blocking(process.stdout.fileno())
        make_non_blocking(process.stderr.fileno())
        
        stdout_data = []
        stderr_data = []
        start_time = time.time()
        
        # Stream output in real-time
        while True:
            # Check if process has finished
            poll_result = process.poll()
            current_time = time.time()
            
            # Check timeout
            if current_time - start_time > timeout:
                process.kill()
                return f"STREAMING OUTPUT:\n{''.join(stdout_data)}\nSTDERR:\n{''.join(stderr_data)}\nERROR: Command timed out after {timeout} seconds"
            
            # Use select to check for available data
            ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
            
            for stream in ready:
                try:
                    if stream == process.stdout:
                        line = process.stdout.readline()
                        if line:
                            stdout_data.append(line)
                            # Emit real-time output to client
                            emit_streaming_output(line, 'stdout')
                    elif stream == process.stderr:
                        line = process.stderr.readline()
                        if line:
                            stderr_data.append(line)
                            # Emit real-time output to client
                            emit_streaming_output(line, 'stderr')
                except:
                    pass  # Ignore blocking errors
            
            # Process finished
            if poll_result is not None:
                # Read any remaining output
                try:
                    remaining_stdout = process.stdout.read()
                    if remaining_stdout:
                        stdout_data.append(remaining_stdout)
                        emit_streaming_output(remaining_stdout, 'stdout')
                except:
                    pass
                
                try:
                    remaining_stderr = process.stderr.read()
                    if remaining_stderr:
                        stderr_data.append(remaining_stderr)
                        emit_streaming_output(remaining_stderr, 'stderr')
                except:
                    pass
                
                break
        
        return f"STREAMING OUTPUT:\n{''.join(stdout_data)}\nSTDERR:\n{''.join(stderr_data)}\nEXIT CODE: {process.returncode}"
        
    except Exception as e:
        return f"Error executing streaming command: {str(e)}"

def emit_streaming_output(data, stream_type):
    """Emit streaming output to the web client if available."""
    try:
        from flask import session as flask_session
        from flask_socketio import emit
        session_id = flask_session.get('session_id')
        if session_id:
            emit('streaming_output', {
                'data': data,
                'stream_type': stream_type,
                'timestamp': datetime.now().isoformat()
            }, room=session_id)
    except:
        pass  # Ignore if not in web context