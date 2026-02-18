#!/usr/bin/env python3
"""
VoxAI Terminal Mode — Claude Code-style CLI.

Launched from the GUI (or standalone). Shares conversation context via the
project's .vox/conversation.json file.  Streams AI responses to the console
with ANSI colors.

Controls:
    /exit  or Ctrl+C  — quit and return to GUI
    /clear             — clear context
    /export <file>     — export conversation
    /mode              — toggle Phased / Siege
    /help              — show commands
"""

import argparse
import json
import os
import re
import sys
import time

# Ensure project root is importable
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    ITALIC  = "\033[3m"
    CYAN    = "\033[36m"
    ORANGE  = "\033[38;5;208m"
    GREEN   = "\033[32m"
    RED     = "\033[31m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"


def _enable_ansi_windows():
    """Enable VT100 escape processing on Windows 10+."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


BANNER = rf"""
{C.CYAN}{C.BOLD}
 ██╗   ██╗ ██████╗ ██╗  ██╗ █████╗ ██╗
 ██║   ██║██╔═══██╗╚██╗██╔╝██╔══██╗██║
 ██║   ██║██║   ██║ ╚███╔╝ ███████║██║
 ╚██╗ ██╔╝██║   ██║ ██╔██╗ ██╔══██║██║
  ╚████╔╝ ╚██████╔╝██╔╝ ██╗██║  ██║██║
   ╚═══╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝{C.RESET}

{C.ORANGE}{C.BOLD}  T E R M I N A L   M O D E{C.RESET}
{C.GRAY}  ─────────────────────────────────────
  Type to chat  │  /help for commands
  /exit to quit │  Returns to GUI on exit
  ─────────────────────────────────────{C.RESET}
"""

HELP_TEXT = f"""
{C.CYAN}Commands:{C.RESET}
  {C.ORANGE}/exit{C.RESET}          — Quit terminal, return to GUI
  {C.ORANGE}/clear{C.RESET}         — Clear conversation context
  {C.ORANGE}/export <file>{C.RESET} — Export conversation to file
  {C.ORANGE}/mode{C.RESET}          — Toggle Phased / Siege mode
  {C.ORANGE}/model{C.RESET}         — Show current model
  {C.ORANGE}/status{C.RESET}        — Show git status
  {C.ORANGE}/help{C.RESET}          — Show this help
"""


def _shell_quote(s: str) -> str:
    """Escape a string for safe shell interpolation."""
    return "'" + s.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# Core engine (reuses project's modules)
# ---------------------------------------------------------------------------
class TerminalEngine:
    def __init__(self, project_root: str, conv_file: str,
                 model: str, mode: str):
        os.chdir(project_root)
        from core.agent_tools import set_project_root
        set_project_root(project_root)

        from core.settings import SettingsManager
        from core.ai_client import AIClient
        from core.code_parser import CodeParser
        from core.agent_tools import AgentToolHandler
        from core.prompts import SystemPrompts

        self.settings = SettingsManager()
        self.settings.set_selected_model(model)
        self.project_root = project_root
        self.conv_file = conv_file
        self.model = model
        self.mode = mode  # "phased" or "siege"
        self.messages: list[dict] = []
        self.tool_loop_limit = 25 if "siege" in mode.lower() else 3

        self._load_conversation()

    def _load_conversation(self):
        if self.conv_file and os.path.exists(self.conv_file):
            try:
                with open(self.conv_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.messages = data.get("messages", [])
                n = len(self.messages)
                print(f"{C.GREEN}  Loaded {n} messages from GUI session{C.RESET}")
            except Exception as e:
                print(f"{C.RED}  Failed to load conversation: {e}{C.RESET}")

    def save_conversation(self):
        if not self.conv_file:
            return
        try:
            parent = os.path.dirname(self.conv_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            data = {"conversation_id": "terminal",
                    "messages": self.messages}
            with open(self.conv_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{C.RED}  Save failed: {e}{C.RESET}")

    def clear(self):
        self.messages = []
        print(f"{C.YELLOW}  Context cleared.{C.RESET}")

    def toggle_mode(self):
        if "siege" in self.mode.lower():
            self.mode = "phased"
            self.tool_loop_limit = 3
        else:
            self.mode = "siege"
            self.tool_loop_limit = 25
        print(f"{C.ORANGE}  Mode: {self.mode.upper()}{C.RESET}")

    def export(self, path: str):
        try:
            lines = []
            for m in self.messages:
                role = m.get("role", "?").upper()
                content = m.get("content", "")
                lines.append(f"## {role}\n\n{content}\n\n---\n")
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"{C.GREEN}  Exported to {path}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}  Export failed: {e}{C.RESET}")

    def chat(self, user_text: str):
        """Send user message, stream AI response, handle tools."""
        self.messages.append({"role": "user", "content": user_text})

        from core.prompts import SystemPrompts
        from core.ai_client import AIClient
        from core.code_parser import CodeParser

        is_local = "local" in self.model.lower()
        base_prompt = (SystemPrompts.CODING_AGENT_LITE if is_local
                       else SystemPrompts.CODING_AGENT)
        base_prompt = base_prompt.replace("{cwd_path}", self.project_root)

        history = [{"role": "system", "content": base_prompt}]

        if "siege" in self.mode.lower() and not is_local:
            history.append({"role": "system", "content":
                "COMMAND & CONTROL: MODE 2 (SIEGE MODE / FULL AUTO)\n"
                "AUTHORIZATION GRANTED: \"GO LIMITLESS\"\n"
                "Execute all phases without pausing. DO NOT STOP.\n\n"
                "FINAL SUMMARY (CRITICAL): When the task is COMPLETE, end with a "
                "detailed summary of what you did, key findings, and next steps. "
                "NEVER end with just \"Done\"."})
        elif not is_local:
            history.append({"role": "system", "content":
                "COMMAND & CONTROL: MODE 1 (PHASED)\n"
                "Execute one phase at a time. After [TOOL_RESULT], write a "
                "DETAILED SUMMARY of what was done, what was found, your assessment, "
                "and next steps. NEVER say just \"Phase completed\". STOP after the summary."})

        recent = self.messages[-40:]
        history.extend(recent)

        ai = AIClient()
        tool_loops = 0

        while True:
            response = self._stream_response(ai, history)
            if not response:
                break

            self.messages.append({"role": "assistant", "content": response})

            # Strip <thought> blocks for display (already streamed)
            display = re.sub(r'<thought>.*?</thought>\s*', '', response, flags=re.DOTALL).strip()

            # Parse tool calls
            tools = CodeParser.parse_tool_calls(response)
            if not tools:
                break

            tool_loops += 1
            if tool_loops >= self.tool_loop_limit:
                print(f"\n{C.YELLOW}  [Phase gate: {self.tool_loop_limit} tool cycles. "
                      f"Send a message to continue.]{C.RESET}")
                break

            tool_output = self._execute_tools(tools)
            tool_msg = (
                "[TOOL_RESULT] (Automated system output — not user input)\n"
                f"{tool_output}\n[/TOOL_RESULT]")
            self.messages.append({"role": "user", "content": tool_msg})
            history.append({"role": "assistant", "content": response})
            history.append({"role": "user", "content": tool_msg})

        self.save_conversation()

    def _stream_response(self, ai, history: list) -> str:
        """Stream AI response to terminal with ANSI colors."""
        print(f"\n{C.CYAN}{C.BOLD}VoxAI{C.RESET} ", end="", flush=True)
        full_response = ""
        in_thought = False
        try:
            for chunk in ai.stream_chat(history):
                if not chunk:
                    continue
                full_response += chunk

                # Dim <thought> blocks
                if '<thought>' in chunk:
                    in_thought = True
                    chunk = chunk.replace('<thought>', '')
                    print(f"{C.GRAY}{C.ITALIC}", end="", flush=True)
                if '</thought>' in chunk:
                    in_thought = False
                    chunk = chunk.replace('</thought>', '')
                    print(f"{C.RESET}", end="", flush=True)
                    if not chunk.strip():
                        continue

                # Colorize tool calls inline
                clean = chunk.replace('<thought>', '').replace('</thought>', '')
                if in_thought:
                    print(f"{C.GRAY}{clean}{C.RESET}", end="", flush=True)
                else:
                    print(clean, end="", flush=True)

        except KeyboardInterrupt:
            print(f"\n{C.YELLOW}  [Interrupted]{C.RESET}")
        except Exception as e:
            print(f"\n{C.RED}  [Error: {e}]{C.RESET}")
        print()  # newline after response
        return full_response

    def _execute_tools(self, tools: list) -> str:
        """Execute tool calls and return combined output."""
        from core.agent_tools import AgentToolHandler
        outputs = []

        for call in tools:
            cmd = call['cmd']
            args = call['args']
            print(f"  {C.ORANGE}⚡ {cmd}{C.RESET}", end="")

            try:
                if cmd == 'read_file':
                    path = args.get('path')
                    start = int(args.get('start_line', 1))
                    end = int(args.get('end_line', 300))
                    result = AgentToolHandler.read_file(path, start_line=start, end_line=end)
                    outputs.append(f"Read '{path}':\n{result}")
                    print(f" {C.GREEN}✓{C.RESET} {path}")

                elif cmd == 'write_file':
                    path = args.get('path')
                    content = args.get('content')
                    syntax = AgentToolHandler.validate_syntax(content, path)
                    if syntax:
                        outputs.append(f"Syntax error in '{path}': {syntax}")
                        print(f" {C.RED}✗{C.RESET} syntax error")
                        continue
                    result = AgentToolHandler.write_file(path, content)
                    outputs.append(f"Wrote '{path}': {result}")
                    print(f" {C.GREEN}✓{C.RESET} {path}")

                elif cmd == 'edit_file':
                    path = args.get('path')
                    old = args.get('old_text', args.get('content', ''))
                    new = args.get('new_text', '')
                    result = AgentToolHandler.edit_file(path, old, new)
                    outputs.append(f"Edit '{path}': {result}")
                    print(f" {C.GREEN}✓{C.RESET} {path}")

                elif cmd == 'list_files':
                    path = args.get('path', '.')
                    result = AgentToolHandler.list_files(path)
                    outputs.append(f"Files in '{path}':\n{result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd == 'search_files':
                    query = args.get('query')
                    root = args.get('root_dir', '.')
                    result = AgentToolHandler.search_files(query, root)
                    outputs.append(f"Search '{query}':\n{result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd == 'execute_command':
                    command = args.get('command')
                    print(f" {C.YELLOW}{command}{C.RESET}")
                    result = AgentToolHandler.execute_command(command)
                    outputs.append(f"Command output:\n{result}")

                elif cmd == 'delete_file':
                    path = args.get('path')
                    result = AgentToolHandler.delete_file(path)
                    outputs.append(f"Delete: {result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd in ('move_file', 'copy_file'):
                    src, dst = args.get('src'), args.get('dst')
                    fn = AgentToolHandler.move_file if cmd == 'move_file' else AgentToolHandler.copy_file
                    result = fn(src, dst)
                    outputs.append(f"{cmd}: {result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd == 'get_file_structure':
                    path = args.get('path')
                    result = AgentToolHandler.get_file_structure(path)
                    outputs.append(f"Structure of '{path}':\n{result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd in ('git_status', 'git_diff', 'git_log', 'git_commit',
                             'git_push', 'git_pull', 'git_fetch'):
                    remote = args.get('remote', 'origin')
                    branch = args.get('branch', '')
                    git_cmds = {
                        'git_status': 'git status --short',
                        'git_diff': 'git diff' + (f" {args.get('path','')}" if args.get('path') else ''),
                        'git_log': f"git log --oneline -n {args.get('count','15')}",
                        'git_commit': 'git add -A && git commit -m ' + _shell_quote(args.get("message", "auto-commit")),
                        'git_push': f"git push {remote} {branch}".strip(),
                        'git_pull': f"git pull {remote} {branch}".strip(),
                        'git_fetch': f"git fetch {remote}".strip(),
                    }
                    git_cmd = git_cmds[cmd]
                    result = AgentToolHandler.execute_command(git_cmd)
                    outputs.append(f"Git ({cmd}):\n{result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd == 'web_search':
                    query = args.get('query', '')
                    print(f" {C.BLUE}{query}{C.RESET}")
                    try:
                        from Vox_IronGate import IronGateClient
                        result = IronGateClient.web_search(query)
                    except Exception as e:
                        result = f"[Error: {e}]"
                    outputs.append(f"Web search:\n{result}")

                elif cmd == 'fetch_url':
                    url = args.get('url', '')
                    print(f" {C.BLUE}{url}{C.RESET}")
                    try:
                        from Vox_IronGate import IronGateClient
                        result = IronGateClient.fetch_url(url)
                    except Exception as e:
                        result = f"[Error: {e}]"
                    outputs.append(f"Fetch URL:\n{result}")

                elif cmd in ('search_memory', 'search_codebase'):
                    query = args.get('query', '')
                    try:
                        from core.rag_client import RAGClient
                        rag = RAGClient()
                        chunks = rag.retrieve(query)
                        if chunks:
                            result = rag.format_context_block(chunks)
                        else:
                            result = "No relevant results found."
                    except Exception as e:
                        result = f"[Error: {e}]"
                    outputs.append(f"Memory/Codebase search:\n{result}")
                    print(f" {C.GREEN}✓{C.RESET}")

                elif cmd == 'index_codebase':
                    path = args.get('path', '.')
                    try:
                        from core.indexer import ProjectIndexer
                        indexer = ProjectIndexer()
                        indexer.index_project(path)
                        result = f"Indexed {path}"
                    except Exception as e:
                        result = f"[Error: {e}]"
                    outputs.append(result)
                    print(f" {C.GREEN}✓{C.RESET}")

                else:
                    outputs.append(f"Unknown tool: {cmd}")
                    print(f" {C.RED}?{C.RESET}")

            except Exception as e:
                outputs.append(f"[TOOL_ERROR] {cmd}: {e}")
                print(f" {C.RED}✗ {e}{C.RESET}")

        return "\n\n".join(outputs)


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------
def main():
    _enable_ansi_windows()

    parser = argparse.ArgumentParser(description="VoxAI Terminal Mode")
    parser.add_argument("--project", default=os.getcwd())
    parser.add_argument("--conversation", default="")
    parser.add_argument("--model", default="[OpenRouter] openrouter/auto")
    parser.add_argument("--mode", default="phased")
    args = parser.parse_args()

    print(BANNER)
    print(f"  {C.GRAY}Project: {args.project}{C.RESET}")
    print(f"  {C.GRAY}Model:   {args.model}{C.RESET}")
    print(f"  {C.GRAY}Mode:    {args.mode}{C.RESET}")
    print()

    engine = TerminalEngine(
        project_root=args.project,
        conv_file=args.conversation,
        model=args.model,
        mode=args.mode,
    )

    while True:
        try:
            user_input = input(f"{C.ORANGE}{C.BOLD}> {C.RESET}")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C.YELLOW}  Exiting terminal mode...{C.RESET}")
            break

        text = user_input.strip()
        if not text:
            continue

        if text.lower() in ("/exit", "/quit", "exit", "quit"):
            print(f"{C.YELLOW}  Returning to GUI...{C.RESET}")
            break

        if text.lower() == "/clear":
            engine.clear()
            continue

        if text.lower() == "/help":
            print(HELP_TEXT)
            continue

        if text.lower() == "/mode":
            engine.toggle_mode()
            continue

        if text.lower() == "/model":
            print(f"  {C.CYAN}Model: {engine.model}{C.RESET}")
            continue

        if text.lower() == "/status":
            import subprocess
            try:
                r = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=engine.project_root,
                    capture_output=True, text=True, timeout=5)
                print(r.stdout if r.stdout else "  Clean working tree")
            except Exception as e:
                print(f"  {C.RED}{e}{C.RESET}")
            continue

        if text.lower().startswith("/export"):
            parts = text.split(maxsplit=1)
            path = parts[1] if len(parts) > 1 else "conversation_export.md"
            engine.export(path)
            continue

        engine.chat(text)

    engine.save_conversation()
    print(f"\n{C.CYAN}  Session saved. Goodbye.{C.RESET}\n")


if __name__ == "__main__":
    main()
