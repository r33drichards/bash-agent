import base64
import matplotlib.pyplot as plt
import matplotlib
import io
import contextlib
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output

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

def execute_ipython(code, print_result=False):
    """Execute Python code using IPython and return stdout, stderr, and rich output."""
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