from terminal_bench.agents.base_agent import BaseAgent, AgentResult
from terminal_bench.terminal.tmux_session import TmuxSession

import os
import time
import json
import asyncio
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

from agent.llm import LLM
from agent.tool_execution import execute_tool_call, get_mcp_loop
from agent.mcp_client import initialize_mcp_client, get_mcp_client


def _run_in_container(container: Any, command: str, timeout: int = 60) -> Tuple[str, int]:
    """Execute a shell command in the given container if supported."""
    try:
        # docker-py style API
        if container is not None and hasattr(container, "exec_run"):
            result = container.exec_run(["bash", "-lc", command], demux=True)
            stdout, stderr = result.output if hasattr(result, "output") else result
            if isinstance(stdout, (bytes, bytearray)):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, (bytes, bytearray)):
                stderr = stderr.decode("utf-8", errors="replace")
            exit_code = getattr(result, "exit_code", 0)
            combined = f"STDOUT:\n{stdout or ''}\nSTDERR:\n{stderr or ''}"
            return combined, exit_code
    except Exception as e:
        return f"Error executing in container: {e}", 1
    return "Container execution not available", 127


def _run_in_tmux(session: TmuxSession, command: str, timeout: int = 60) -> Tuple[str, int]:
    """Best-effort command execution via TmuxSession."""
    # Try common helper methods first
    try:
        if hasattr(session, "run"):
            result = session.run(command, timeout=timeout)  # type: ignore[attr-defined]
            if isinstance(result, tuple) and len(result) == 2:
                return str(result[0]), int(result[1])
            if isinstance(result, dict):
                return str(result.get("output", "")), int(result.get("exit_code", 0))
    except Exception:
        pass

    try:
        if hasattr(session, "run_command"):
            result = session.run_command(command, timeout=timeout)  # type: ignore[attr-defined]
            if isinstance(result, tuple) and len(result) == 2:
                return str(result[0]), int(result[1])
            if isinstance(result, dict):
                return str(result.get("output", "")), int(result.get("exit_code", 0))
    except Exception:
        pass

    # Fallback: send keys and capture pane
    try:
        send = getattr(session, "send_keys", None)
        capture = getattr(session, "capture_pane", None)
        if callable(send) and callable(capture):
            send(command)
            send("\n")
            # crude wait; tasks usually short, adjust if needed
            time.sleep(min(max(timeout, 1), 60) * 0.2)
            captured = capture()  # type: ignore[call-arg]
            if isinstance(captured, (list, tuple)):
                output = "\n".join(str(x) for x in captured)
            else:
                output = str(captured)
            return output, 0
    except Exception as e:
        return f"Error executing in tmux: {e}", 1

    return "Tmux execution not available", 127


def _execute_bash(session: TmuxSession, container: Any, command: str, timeout: int = 60) -> str:
    """Execute bash in the benchmark environment, preferring container > tmux > host."""
    # Prefer container when present
    if container is not None:
        out, code = _run_in_container(container, command, timeout)
        return f"{out}\nEXIT CODE: {code}"

    # Fallback to tmux session
    if session is not None:
        out, code = _run_in_tmux(session, command, timeout)
        return f"{out}\nEXIT CODE: {code}"

    # Last resort: host execution (not ideal for TB but avoids crashing)
    try:
        import subprocess
        result = subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=timeout)
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nEXIT CODE: {result.returncode}"
    except Exception as e:
        return f"Error executing locally: {e}"


class YourCustomAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "bash-agent"

    def perform_task(
        self,
        instruction: str,
        session: TmuxSession,
        logging_dir: Path | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        # Resolve optional container from kwargs if provided by TB
        container = kwargs.get("container")

        # Initialize MCP client (loads defaults + user config if TB sets env)
        mcp_config = os.environ.get("MCP_CONFIG")
        mcp_loop = get_mcp_loop()
        try:
            fut = asyncio.run_coroutine_threadsafe(
                initialize_mcp_client(mcp_config_path=mcp_config, working_dir=os.getcwd()),
                mcp_loop,
            )
            fut.result(timeout=30)
        except Exception:
            pass

        # Create LLM with MCP and default tools
        model = os.environ.get("ANTHROPIC_MODEL", "claude-3-7-sonnet-latest")
        llm = LLM(model=model, session_id=None)

        # Prepare logs
        logs: list[str] = []
        def log(line: str) -> None:
            timestamped = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}"
            logs.append(timestamped)
            if logging_dir:
                try:
                    logging_dir.mkdir(parents=True, exist_ok=True)
                    with (logging_dir / "agent.log").open("a", encoding="utf-8") as f:
                        f.write(timestamped + "\n")
                except Exception:
                    pass

        log("Starting task")
        log(f"Task: {instruction}")

        # Kick off with the task description
        message = [{"type": "text", "text": instruction}]
        output, tool_calls = llm(message)

        # Loop through tool calls
        max_steps = int(os.environ.get("TB_MAX_STEPS", "20"))
        steps = 0
        final_output = output or ""

        while tool_calls and steps < max_steps:
            steps += 1
            new_results = []
            for tool_call in tool_calls:
                name = tool_call.get("name")
                tool_input = tool_call.get("input", {}) or {}
                log(f"Tool call {steps}: {name}")

                try:
                    # Handle MCP tools directly if available
                    is_mcp = False
                    try:
                        mcp_client = get_mcp_client()
                        if mcp_client and getattr(mcp_client, "available_tools", None):
                            is_mcp = any(t["name"] == name for t in mcp_client.available_tools)
                    except Exception:
                        pass

                    if name == "bash":
                        cmd = tool_input.get("command", "")
                        timeout = int(tool_input.get("timeout", 60))
                        result_text = _execute_bash(session, container, cmd, timeout)
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_call.get("id"),
                            "content": [{"type": "text", "text": result_text}],
                        }
                    elif is_mcp:
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                mcp_client.call_tool(name, tool_input),  # type: ignore[arg-type]
                                mcp_loop,
                            )
                            mcp_result = future.result(timeout=120)
                            if mcp_result.get("error"):
                                txt = str(mcp_result["error"])
                            else:
                                content = mcp_result.get("content")
                                if isinstance(content, list) and content:
                                    first = content[0]
                                    if isinstance(first, dict) and first.get("type") == "text":
                                        txt = first.get("text", "")
                                    elif hasattr(first, "text"):
                                        txt = getattr(first, "text")
                                    else:
                                        txt = json.dumps(content)[:4000]
                                else:
                                    txt = str(content)
                            result = {
                                "type": "tool_result",
                                "tool_use_id": tool_call.get("id"),
                                "content": [{"type": "text", "text": txt}],
                            }
                        except Exception as e:
                            result = {
                                "type": "tool_result",
                                "tool_use_id": tool_call.get("id"),
                                "content": [{"type": "text", "text": f"Error executing MCP tool: {e}"}],
                            }
                    else:
                        # Built-in tools: delegate to shared executor
                        exec_result = execute_tool_call(tool_call)
                        result = exec_result

                    new_results.append(result)
                except Exception as e:
                    new_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call.get("id"),
                            "content": [{"type": "text", "text": f"Tool execution error: {e}"}],
                        }
                    )

            # Feed all tool results back to the LLM in one go (sequentially)
            for res in new_results:
                final_output, tool_calls = llm([res])
                if not tool_calls:
                    break

        # Best-effort result construction
        return AgentResult()