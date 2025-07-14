import os
import subprocess
import argparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import anthropic
from anthropic import RateLimitError, APIError
import sqlite3
import json
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output
import io
import contextlib

from memory import MemoryManager

def main():
    parser = argparse.ArgumentParser(description='LLM Agent with configurable prompt file')
    parser.add_argument('--prompt-file', type=str, default=None, required=False,
                      help='Path to the prompt file (default: prompt.md)')
    # initial user input
    parser.add_argument('--initial-user-input', type=str, default=None, required=False,
                      help='Initial user input (default: None)')
    parser.add_argument('--auto-confirm', action='store_true', help='Automatically confirm all actions without prompting')
    parser.add_argument('--exit-on-user-input', action='store_true', help='Exit immediately after receiving user input (not initial_user_input)')
    args = parser.parse_args()
    
    try:
        print("\n=== LLM Agent Loop with Claude and Bash Tool ===\n")
        print("Type 'exit' to end the conversation.\n")
        loop(
            LLM("claude-3-7-sonnet-latest", args.prompt_file),
            args.initial_user_input,
            args.auto_confirm if hasattr(args, 'auto_confirm') else False,
            args.exit_on_user_input if hasattr(args, 'exit_on_user_input') else False
        )
    except KeyboardInterrupt:
        print("\n\nExiting. Goodbye!")
    except Exception as e:
        print(f"\n\nAn error occurred: {str(e)}")

def loop(llm, initial_user_input=None, auto_confirm=False, exit_on_user_input=False):
    memory_manager = MemoryManager()
    
    if initial_user_input:
        # Load relevant memories for initial input
        relevant_memories = memory_manager.get_memory_context(initial_user_input, max_memories=3)
        if relevant_memories != "No relevant memories found.":
            context_msg = f"{relevant_memories}\n\n=== USER MESSAGE ===\n{initial_user_input}"
            msg = [{"type": "text", "text": context_msg}]
        else:
            msg = [{"type": "text", "text": initial_user_input}]
    else:
        user_msg = user_input()
        if exit_on_user_input:
            print("\nExiting after user input as requested by --exit-on-user-input flag.")
            raise SystemExit(0)
        
        # Load relevant memories for user input
        user_text = user_msg[0]["text"]
        relevant_memories = memory_manager.get_memory_context(user_text, max_memories=3)
        if relevant_memories != "No relevant memories found.":
            context_msg = f"{relevant_memories}\n\n=== USER MESSAGE ===\n{user_text}"
            msg = [{"type": "text", "text": context_msg}]
        else:
            msg = user_msg
            
    while True:
        output, tool_calls = llm(msg)
        print("Agent: ", output)
        if tool_calls:
            msg = [ handle_tool_call(tc, auto_confirm) for tc in tool_calls ]
        else:
            user_msg = user_input()
            # Load relevant memories for new user input
            user_text = user_msg[0]["text"]
            relevant_memories = memory_manager.get_memory_context(user_text, max_memories=3)
            if relevant_memories != "No relevant memories found.":
                context_msg = f"{relevant_memories}\n\n=== USER MESSAGE ===\n{user_text}"
                msg = [{"type": "text", "text": context_msg}]
            else:
                msg = user_msg


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
    import patch
    import os
    try:
        # Write the diff to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8', suffix='.patch') as tmp_patch:
            tmp_patch.write(diff)
            patch_path = tmp_patch.name
        # Apply the patch
        pset = patch.fromfile(patch_path)
        if not pset:
            os.unlink(patch_path)
            return f"Failed to parse patch file."
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

def user_input():
    x = input("You: ")
    if x.lower() in ["exit", "quit"]:
        print("\nExiting agent loop. Goodbye!")
        raise SystemExit(0)
    return [{"type": "text", "text": x}]

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
            """You are a helpful AI assistant with access to bash, sqlite, Python, file editing, and memory tools.\n"""
            "You can help the user by executing commands and interpreting the results.\n"
            "Be careful with destructive commands and always explain what you're doing.\n\n"
            
            "AVAILABLE TOOLS:\n"
            "- bash: Run shell commands\n"
            "- sqlite: Execute SQL queries on SQLite databases\n"  
            "- ipython: Execute Python code with rich output support\n"
            "- edit_file_diff: Apply unified diff patches to files\n"
            "- overwrite_file: Replace entire file contents\n"
            "- Memory tools: save_memory, search_memory, list_memories, get_memory, delete_memory\n\n"
            
            "SQLITE USAGE:\n"
            "For large SELECT queries, you can specify an 'output_json' file path in the sqlite tool input. If you do, write the full result to that file and only print errors or the first record in the response.\n"
            "You can also set 'print_result' to true to print the results in the context window, even if output_json is specified. This is useful for letting you see and reason about the data in context.\n\n"
            
            "PYTHON ENVIRONMENT:\n"
            "When generating plots in Python (e.g., with matplotlib), always save the plot to a file (such as .png) and mention the filename in your response. Do not attempt to display plots inline.\n"
            "The Python environment for the ipython tool includes: numpy, matplotlib, scikit-learn, ipykernel, torch, tqdm, gymnasium, torchvision, tensorboard, torch-tb-profiler, opencv-python, nbconvert, anthropic, seaborn, pandas, tenacity.\n\n"
            
            "MEMORY USAGE:\n"
            "Use the memory tools to store and retrieve important information across conversations:\n"
            "- save_memory: Store important facts, solutions, configurations, or insights\n"
            "- search_memory: Find relevant information from previous sessions\n"
            "- list_memories: Browse all stored memories\n"
            "- get_memory: Retrieve a specific memory by ID\n"
            "- delete_memory: Remove outdated or incorrect memories\n"
            "Always check for relevant memories before starting complex tasks to leverage previous work.\n\n"
            + prompt
        )
        # Add memory tools
        save_memory_tool = {
            "name": "save_memory",
            "description": "Save information to memory for future reference.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "A descriptive title for the memory"},
                    "content": {"type": "string", "description": "The content to store in memory"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags to categorize the memory"}
                },
                "required": ["title", "content"]
            }
        }
        
        search_memory_tool = {
            "name": "search_memory",
            "description": "Search stored memories by content, title, or tags.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query to find relevant memories"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags to filter memories"},
                    "limit": {"type": "integer", "description": "Maximum number of memories to return (default: 10)"}
                }
            }
        }
        
        list_memories_tool = {
            "name": "list_memories",
            "description": "List all stored memories with optional pagination.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum number of memories to return (default: 20)"},
                    "offset": {"type": "integer", "description": "Number of memories to skip (default: 0)"}
                }
            }
        }
        
        get_memory_tool = {
            "name": "get_memory",
            "description": "Retrieve a specific memory by its ID.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "The ID of the memory to retrieve"}
                },
                "required": ["memory_id"]
            }
        }
        
        delete_memory_tool = {
            "name": "delete_memory",
            "description": "Delete a memory by its ID.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "The ID of the memory to delete"}
                },
                "required": ["memory_id"]
            }
        }
        
        self.memory_manager = MemoryManager()
        self.tools = [bash_tool, sqlite_tool, ipython_tool, edit_file_diff_tool, overwrite_file_tool, save_memory_tool, search_memory_tool, list_memories_tool, get_memory_tool, delete_memory_tool]

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

def handle_tool_call(tool_call, auto_confirm=False):
    if tool_call["name"] == "bash":
        command = tool_call["input"]["command"]
        print(f"\nAbout to execute bash command:\n\n{command}")
        if not auto_confirm:
            confirm = input("Enter to confirm or x to cancel").strip().lower()
        else:
            print("[Auto-confirm enabled: proceeding without prompt]")
            confirm = ""
        if confirm == "x":
            print("Command execution skipped by user.")
            output_text = "Command execution was skipped by user confirmation. Seek user input for next steps"
        else:
            print(f"Executing bash command: {command}")
            output_text = execute_bash(command)
            print(f"Bash output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(
                type="text",
                text=output_text
            )]
        )
    elif tool_call["name"] == "sqlite":
        db_path = tool_call["input"]["db_path"]
        query = tool_call["input"]["query"]
        output_json = tool_call["input"].get("output_json")
        print_result = tool_call["input"].get("print_result", False)
        print(f"\nAbout to execute SQLite query on {db_path}:\n\n{query}")
        if output_json:
            print(f"Full results will be written to: {output_json}")
        if print_result:
            print("Results will also be printed in the context window.")
        if not auto_confirm:
            confirm = input("Enter to confirm or x to cancel").strip().lower()
        else:
            print("[Auto-confirm enabled: proceeding without prompt]")
            confirm = ""
        if confirm == "x":
            print("SQL execution skipped by user.")
            output_text = "SQL execution was skipped by user confirmation. Seek user input for next steps"
        else:
            print(f"Executing SQL query: {query}")
            output_text = execute_sqlite(db_path, query, output_json, print_result)
            print(f"SQLite output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(
                type="text",
                text=output_text
            )]
        )
    elif tool_call["name"] == "ipython":
        code = tool_call["input"]["code"]
        print_result = tool_call["input"].get("print_result", False)
        print(f"\nAbout to execute Python code with IPython:\n\n{code}")
        if print_result:
            print("Result will also be printed in the context window.")
        if not auto_confirm:
            confirm = input("Enter to confirm or x to cancel").strip().lower()
        else:
            print("[Auto-confirm enabled: proceeding without prompt]")
            confirm = ""
        if confirm == "x":
            print("Python execution skipped by user.")
            output_text = "Python execution was skipped by user confirmation. Seek user input for next steps"
        else:
            print(f"Executing Python code:")
            output_text = execute_ipython(code, print_result)
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(
                type="text",
                text=output_text
            )]
        )
    elif tool_call["name"] == "edit_file_diff":
        file_path = tool_call["input"]["file_path"]
        diff = tool_call["input"]["diff"]
        print(f"\nAbout to apply unified diff to {file_path}:")
        print(diff)
        # Preview the result of applying the diff
        import tempfile
        import shutil
        import patch
        preview_success = False
        try:
            with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8', suffix='.patch') as tmp_patch:
                tmp_patch.write(diff)
                patch_path = tmp_patch.name
            with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8') as tmp_file:
                preview_path = tmp_file.name
            shutil.copyfile(file_path, preview_path)
            pset = patch.fromfile(patch_path)
            if pset:
                # Patch expects the file to be in the current directory, so chdir
                cwd = os.getcwd()
                try:
                    os.chdir(os.path.dirname(preview_path) or ".")
                    # Patch the temp file (patch library works on filenames)
                    # We need to adjust the filenames in the patch object to match the temp file
                    for patched_file in pset.items:
                        patched_file.target = os.path.basename(preview_path)
                        patched_file.source = os.path.basename(preview_path)
                    result = pset.apply()
                finally:
                    os.chdir(cwd)
                if result:
                    with open(preview_path, 'r', encoding='utf-8') as f:
                        preview_content = f.read()
                    print("\n--- Preview of file after applying diff ---\n")
                    print(preview_content)
                    preview_success = True
                else:
                    print("\n[Preview failed: could not apply diff to temp file]")
            else:
                print("\n[Preview failed: could not parse diff]")
        except Exception as e:
            print(f"[Preview error: {e}]")
        finally:
            try:
                os.unlink(patch_path)
            except Exception:
                pass
            try:
                os.unlink(preview_path)
            except Exception:
                pass
        if not auto_confirm:
            confirm = input("Enter to confirm or x to cancel").strip().lower()
        else:
            print("[Auto-confirm enabled: proceeding without prompt]")
            confirm = ""
        if confirm == "x":
            print("Diff application skipped by user.")
            output_text = "Diff application was skipped by user confirmation. Seek user input for next steps"
        else:
            print(f"Applying diff to {file_path}")
            output_text = apply_unified_diff(file_path, diff)
            print(f"Diff output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(
                type="text",
                text=output_text
            )]
        )
    elif tool_call["name"] == "overwrite_file":
        file_path = tool_call["input"]["file_path"]
        content = tool_call["input"]["content"]
        print(f"\nAbout to overwrite {file_path} with new content.")
        print("\n--- Preview of new file content ---\n")
        print(content)
        if not auto_confirm:
            confirm = input("Enter to confirm or x to cancel").strip().lower()
        else:
            print("[Auto-confirm enabled: proceeding without prompt]")
            confirm = ""
        if confirm == "x":
            print("Overwrite skipped by user.")
            output_text = "Overwrite was skipped by user confirmation. Seek user input for next steps"
        else:
            print(f"Overwriting {file_path}")
            output_text = overwrite_file(file_path, content)
            print(f"Overwrite output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(
                type="text",
                text=output_text
            )]
        )
    elif tool_call["name"] == "save_memory":
        title = tool_call["input"]["title"]
        content = tool_call["input"]["content"]
        tags = tool_call["input"].get("tags", [])
        print(f"\nSaving memory: {title}")
        memory_manager = MemoryManager()
        try:
            memory_id = memory_manager.save_memory(title, content, tags)
            output_text = f"Memory saved successfully with ID: {memory_id}\nTitle: {title}"
        except Exception as e:
            output_text = f"Error saving memory: {str(e)}"
        print(f"Memory output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "search_memory":
        query = tool_call["input"].get("query")
        tags = tool_call["input"].get("tags")
        limit = tool_call["input"].get("limit", 10)
        print(f"\nSearching memories: query='{query}', tags={tags}, limit={limit}")
        memory_manager = MemoryManager()
        try:
            memories = memory_manager.search_memories(query, tags, limit)
            if not memories:
                output_text = "No memories found matching the search criteria."
            else:
                result_lines = [f"Found {len(memories)} memories:"]
                for memory in memories:
                    result_lines.append(f"\nID: {memory['id']}")
                    result_lines.append(f"Title: {memory['title']}")
                    if memory['tags']:
                        result_lines.append(f"Tags: {', '.join(memory['tags'])}")
                    result_lines.append(f"Content: {memory['content']}")
                    result_lines.append(f"Created: {memory['created_at']}")
                    result_lines.append("---")
                output_text = "\n".join(result_lines)
        except Exception as e:
            output_text = f"Error searching memories: {str(e)}"
        print(f"Search output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "list_memories":
        limit = tool_call["input"].get("limit", 20)
        offset = tool_call["input"].get("offset", 0)
        print(f"\nListing memories: limit={limit}, offset={offset}")
        memory_manager = MemoryManager()
        try:
            memories = memory_manager.list_memories(limit, offset)
            if not memories:
                output_text = "No memories found."
            else:
                result_lines = [f"Listing {len(memories)} memories (limit: {limit}, offset: {offset}):"]
                for memory in memories:
                    result_lines.append(f"\nID: {memory['id']}")
                    result_lines.append(f"Title: {memory['title']}")
                    if memory['tags']:
                        result_lines.append(f"Tags: {', '.join(memory['tags'])}")
                    content_preview = memory['content'][:100] + "..." if len(memory['content']) > 100 else memory['content']
                    result_lines.append(f"Content: {content_preview}")
                    result_lines.append(f"Created: {memory['created_at']}")
                    result_lines.append("---")
                output_text = "\n".join(result_lines)
        except Exception as e:
            output_text = f"Error listing memories: {str(e)}"
        print(f"List output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "get_memory":
        memory_id = tool_call["input"]["memory_id"]
        print(f"\nGetting memory: {memory_id}")
        memory_manager = MemoryManager()
        try:
            memory = memory_manager.get_memory(memory_id)
            if not memory:
                output_text = f"Memory with ID {memory_id} not found."
            else:
                result_lines = [
                    f"Memory ID: {memory['id']}",
                    f"Title: {memory['title']}",
                    f"Content: {memory['content']}"
                ]
                if memory['tags']:
                    result_lines.append(f"Tags: {', '.join(memory['tags'])}")
                result_lines.extend([
                    f"Created: {memory['created_at']}",
                    f"Updated: {memory['updated_at']}",
                    f"Last Accessed: {memory['accessed_at']}"
                ])
                output_text = "\n".join(result_lines)
        except Exception as e:
            output_text = f"Error retrieving memory: {str(e)}"
        print(f"Get output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    elif tool_call["name"] == "delete_memory":
        memory_id = tool_call["input"]["memory_id"]
        print(f"\nDeleting memory: {memory_id}")
        memory_manager = MemoryManager()
        try:
            success = memory_manager.delete_memory(memory_id)
            if success:
                output_text = f"Memory with ID {memory_id} deleted successfully."
            else:
                output_text = f"Memory with ID {memory_id} not found or could not be deleted."
        except Exception as e:
            output_text = f"Error deleting memory: {str(e)}"
        print(f"Delete output:\n{output_text}")
        return dict(
            type="tool_result",
            tool_use_id=tool_call["id"],
            content=[dict(type="text", text=output_text)]
        )
    else:
        raise Exception(f"Unsupported tool: {tool_call['name']}")

if __name__ == "__main__":
    main()