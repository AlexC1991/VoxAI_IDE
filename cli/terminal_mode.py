#!/usr/bin/env python3
"""
VoxAI Terminal Mode — Claude Code-style CLI.

Launched from the GUI (or standalone). Shares conversation context via the
project's .vox/history/<conv>.json file.  Streams AI responses with ANSI
colors and supports slash commands for git, model switching, and more.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

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
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
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
{C.CYAN}{C.BOLD}Chat{C.RESET}
  Just type a message to talk to VoxAI.

{C.CYAN}{C.BOLD}General{C.RESET}
  {C.ORANGE}/help{C.RESET}               Show this help
  {C.ORANGE}/exit{C.RESET}               Quit terminal, return to GUI
  {C.ORANGE}/clear{C.RESET}              Clear conversation context
  {C.ORANGE}/export <file>{C.RESET}      Export conversation to file

{C.CYAN}{C.BOLD}Model & Mode{C.RESET}
  {C.ORANGE}/model{C.RESET}              Show current model
  {C.ORANGE}/model <name>{C.RESET}       Switch to a different model
  {C.ORANGE}/models{C.RESET}             List all enabled models
  {C.ORANGE}/mode{C.RESET}               Toggle Phased / Siege mode

{C.CYAN}{C.BOLD}Git{C.RESET}
  {C.ORANGE}/status{C.RESET}             git status --short
  {C.ORANGE}/branch{C.RESET}             Show current branch
  {C.ORANGE}/branches{C.RESET}           List all branches
  {C.ORANGE}/log [n]{C.RESET}            git log --oneline (default 10)
  {C.ORANGE}/diff [file]{C.RESET}        git diff (optionally for one file)
  {C.ORANGE}/commit <msg>{C.RESET}       git add -A && git commit -m <msg>
  {C.ORANGE}/push [remote] [branch]{C.RESET}
  {C.ORANGE}/pull [remote] [branch]{C.RESET}
  {C.ORANGE}/fetch [remote]{C.RESET}
  {C.ORANGE}/stash{C.RESET}              git stash
  {C.ORANGE}/stash pop{C.RESET}          git stash pop
  {C.ORANGE}/checkout <branch>{C.RESET}  Switch branch

{C.CYAN}{C.BOLD}Project{C.RESET}
  {C.ORANGE}/files [path]{C.RESET}       List project files
  {C.ORANGE}/search <query>{C.RESET}     Search across files
  {C.ORANGE}/run <command>{C.RESET}      Execute a shell command
  {C.ORANGE}/index{C.RESET}              Re-index project for RAG
  {C.ORANGE}/tokens{C.RESET}             Show conversation token estimate
"""


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout or error string."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if r.returncode != 0 and r.stderr.strip():
            out = r.stderr.strip() if not out else out + "\n" + r.stderr.strip()
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "(git command timed out)"
    except Exception as e:
        return f"(error: {e})"


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
class TerminalEngine:
    def __init__(self, project_root: str, conv_file: str,
                 model: str, mode: str):
        os.chdir(project_root)
        from core.agent_tools import set_project_root
        set_project_root(project_root)

        from core.settings import SettingsManager

        self.settings = SettingsManager()
        self.settings.set_selected_model(model)
        self.project_root = project_root
        self.conv_file = conv_file
        self.model = model
        self.mode = mode
        self.messages: list[dict] = []
        self.conversation_id = "terminal"
        self._stop_requested = False
        self.tool_loop_limit = 25 if "siege" in mode.lower() else 3

        self._load_conversation()

    # ── Model management ──
    def list_models(self):
        models = self.settings.get_enabled_models() or []
        if not models:
            print(f"  {C.YELLOW}No models configured.{C.RESET}")
            return
        print(f"  {C.CYAN}Enabled models:{C.RESET}")
        for i, m in enumerate(models, 1):
            marker = f"{C.GREEN}→{C.RESET}" if m == self.model else " "
            print(f"  {marker} {C.GRAY}{i}.{C.RESET} {m}")

    def switch_model(self, name: str):
        models = self.settings.get_enabled_models() or []
        # Match by number
        try:
            idx = int(name) - 1
            if 0 <= idx < len(models):
                self.model = models[idx]
                self.settings.set_selected_model(self.model)
                print(f"  {C.GREEN}Switched to: {self.model}{C.RESET}")
                return
        except ValueError:
            pass
        # Match by substring
        matches = [m for m in models if name.lower() in m.lower()]
        if len(matches) == 1:
            self.model = matches[0]
            self.settings.set_selected_model(self.model)
            print(f"  {C.GREEN}Switched to: {self.model}{C.RESET}")
        elif len(matches) > 1:
            print(f"  {C.YELLOW}Ambiguous — matches:{C.RESET}")
            for m in matches:
                print(f"    {m}")
        else:
            print(f"  {C.RED}No model matching '{name}'. Use /models to see available.{C.RESET}")

    # ── Conversation ──
    def _load_conversation(self):
        if self.conv_file and os.path.exists(self.conv_file):
            try:
                with open(self.conv_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.messages = data.get("messages", [])
                conv_id = data.get("conversation_id")
                if isinstance(conv_id, str) and conv_id.strip():
                    self.conversation_id = conv_id.strip()
                elif self.conv_file:
                    self.conversation_id = os.path.splitext(
                        os.path.basename(self.conv_file))[0]
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
            data = {
                "conversation_id": self.conversation_id or "terminal",
                "messages": self.messages,
            }
            with open(self.conv_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            pointer = os.path.join(parent, "current.txt")
            with open(pointer, 'w', encoding='utf-8') as f:
                f.write(self.conversation_id or "terminal")
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

    def show_tokens(self):
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        est_tokens = total_chars // 4
        print(f"  {C.CYAN}Messages: {len(self.messages)}  |  "
              f"~{est_tokens:,} tokens  ({total_chars:,} chars){C.RESET}")

    def export(self, path: str):
        try:
            abs_path = os.path.abspath(path)
            project_root = os.path.abspath(os.getcwd())
            if not abs_path.startswith(project_root):
                print(f"{C.RED}  Export path must be within the project directory.{C.RESET}")
                return
            lines = []
            for m in self.messages:
                role = m.get("role", "?").upper()
                content = m.get("content", "")
                lines.append(f"## {role}\n\n{content}\n\n---\n")
            parent = os.path.dirname(abs_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"{C.GREEN}  Exported to {abs_path}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}  Export failed: {e}{C.RESET}")

    # ── AI chat ──
    def chat(self, user_text: str):
        self._stop_requested = False
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
            if self._stop_requested:
                self.messages.append({"role": "system", "content": "[Interrupted by user]"})
                break

            self.messages.append({"role": "assistant", "content": response})
            re.sub(r'<thought>.*?</thought>\s*', '', response, flags=re.DOTALL).strip()

            tools = CodeParser.parse_tool_calls(response)
            if not tools:
                break

            tool_loops += 1
            if tool_loops >= self.tool_loop_limit:
                print(f"\n{C.YELLOW}  [Phase gate: {self.tool_loop_limit} tool cycles. "
                      f"Send a message to continue.]{C.RESET}")
                break

            tool_output = self._execute_tools(tools)
            if self._stop_requested:
                self.messages.append({"role": "system", "content": "[Interrupted by user]"})
                break
            tool_msg = (
                "[TOOL_RESULT] (Automated system output — not user input)\n"
                f"{tool_output}\n[/TOOL_RESULT]")
            self.messages.append({"role": "user", "content": tool_msg})
            history.append({"role": "assistant", "content": response})
            history.append({"role": "user", "content": tool_msg})

        self.save_conversation()

    def _stream_response(self, ai, history: list) -> str:
        print(f"\n{C.CYAN}{C.BOLD}VoxAI{C.RESET} ", end="", flush=True)
        full_response = ""
        in_thought = False
        try:
            for chunk in ai.stream_chat(history):
                if not chunk:
                    continue
                full_response += chunk

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

                clean = chunk.replace('<thought>', '').replace('</thought>', '')
                if in_thought:
                    print(f"{C.GRAY}{clean}{C.RESET}", end="", flush=True)
                else:
                    print(clean, end="", flush=True)

        except KeyboardInterrupt:
            self._stop_requested = True
            print(f"\n{C.YELLOW}  [Interrupted]{C.RESET}")
        except Exception as e:
            print(f"\n{C.RED}  [Error: {e}]{C.RESET}")
        print()
        return full_response

    def _execute_tools(self, tools: list) -> str:
        from core.agent_tools import AgentToolHandler
        outputs = []

        for call in tools:
            if self._stop_requested:
                outputs.append("[Interrupted] Tool execution stopped by user.")
                break
            cmd = call['cmd']
            args = call['args']
            print(f"  {C.ORANGE}⚡ {cmd}{C.RESET}", end="")

            try:
                if cmd == 'read_file':
                    path = args.get('path')
                    start = int(args.get('start_line', 1))
                    end = int(args.get('end_line', 150))
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
                    remote = _shell_quote(args.get('remote', 'origin'))
                    branch = _shell_quote(args.get('branch', '')) if args.get('branch') else ''
                    try:
                        count = str(max(1, int(args.get('count', 15))))
                    except (ValueError, TypeError):
                        count = '15'
                    diff_path = _shell_quote(args.get('path', '')) if args.get('path') else ''
                    git_cmds = {
                        'git_status': 'git status --short',
                        'git_diff': f'git diff {diff_path}'.strip(),
                        'git_log': f'git log --oneline -n {count}',
                        'git_commit': 'git add -A && git commit -m ' + _shell_quote(args.get("message", "auto-commit")),
                        'git_push': f'git push {remote} {branch}'.strip(),
                        'git_pull': f'git pull {remote} {branch}'.strip(),
                        'git_fetch': f'git fetch {remote}'.strip(),
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

            except KeyboardInterrupt:
                self._stop_requested = True
                outputs.append(f"[Interrupted] {cmd} aborted by user.")
                print(f" {C.YELLOW}⏹ interrupted{C.RESET}")
                break
            except Exception as e:
                outputs.append(f"[TOOL_ERROR] {cmd}: {e}")
                print(f" {C.RED}✗ {e}{C.RESET}")

        return "\n\n".join(outputs)


# ---------------------------------------------------------------------------
# Slash-command dispatcher
# ---------------------------------------------------------------------------
def _handle_slash(text: str, engine: TerminalEngine) -> bool:
    """Handle a slash command. Returns True if handled, False otherwise."""
    lower = text.lower()
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    # ── General ──
    if cmd in ("/exit", "/quit"):
        print(f"{C.YELLOW}  Returning to GUI...{C.RESET}")
        return "EXIT"

    if cmd == "/clear":
        engine.clear()
        return True

    if cmd == "/help":
        print(HELP_TEXT)
        return True

    # ── Model & Mode ──
    if cmd == "/mode":
        engine.toggle_mode()
        return True

    if cmd == "/model":
        if rest:
            engine.switch_model(rest)
        else:
            print(f"  {C.CYAN}Model: {engine.model}{C.RESET}")
        return True

    if cmd == "/models":
        engine.list_models()
        return True

    if cmd == "/tokens":
        engine.show_tokens()
        return True

    # ── Git ──
    root = engine.project_root

    if cmd == "/status":
        print(_git(["status", "--short"], root))
        return True

    if cmd == "/branch":
        print(_git(["rev-parse", "--abbrev-ref", "HEAD"], root))
        return True

    if cmd == "/branches":
        print(_git(["branch", "-a"], root))
        return True

    if cmd == "/log":
        n = rest if rest.isdigit() else "10"
        print(_git(["log", "--oneline", "-n", n], root))
        return True

    if cmd == "/diff":
        args = ["diff"]
        if rest:
            args.append(rest)
        print(_git(args, root))
        return True

    if cmd == "/commit":
        if not rest:
            print(f"  {C.RED}Usage: /commit <message>{C.RESET}")
            return True
        print(_git(["add", "-A"], root))
        print(_git(["commit", "-m", rest], root))
        return True

    if cmd == "/push":
        args = ["push"]
        if rest:
            args.extend(rest.split())
        else:
            args.extend(["origin", "HEAD"])
        print(_git(args, root))
        return True

    if cmd == "/pull":
        args = ["pull"]
        if rest:
            args.extend(rest.split())
        print(_git(args, root))
        return True

    if cmd == "/fetch":
        args = ["fetch"]
        if rest:
            args.append(rest)
        print(_git(args, root))
        return True

    if cmd == "/stash":
        if rest.lower() == "pop":
            print(_git(["stash", "pop"], root))
        elif rest.lower() == "list":
            print(_git(["stash", "list"], root))
        elif rest:
            print(_git(["stash", rest], root))
        else:
            print(_git(["stash"], root))
        return True

    if cmd == "/checkout":
        if not rest:
            print(f"  {C.RED}Usage: /checkout <branch>{C.RESET}")
            return True
        print(_git(["checkout", rest], root))
        return True

    # ── Project ──
    if cmd == "/files":
        from core.agent_tools import AgentToolHandler
        result = AgentToolHandler.list_files(rest or ".")
        print(result)
        return True

    if cmd == "/search":
        if not rest:
            print(f"  {C.RED}Usage: /search <query>{C.RESET}")
            return True
        from core.agent_tools import AgentToolHandler
        result = AgentToolHandler.search_files(rest, ".")
        print(result)
        return True

    if cmd == "/run":
        if not rest:
            print(f"  {C.RED}Usage: /run <command>{C.RESET}")
            return True
        from core.agent_tools import AgentToolHandler
        result = AgentToolHandler.execute_command(rest)
        print(result)
        return True

    if cmd == "/index":
        try:
            from core.indexer import ProjectIndexer
            indexer = ProjectIndexer()
            indexer.index_project(engine.project_root)
            print(f"  {C.GREEN}Indexing complete.{C.RESET}")
        except Exception as e:
            print(f"  {C.RED}Index failed: {e}{C.RESET}")
        return True

    if cmd.startswith("/export"):
        path = rest or "conversation_export.md"
        engine.export(path)
        return True

    return False  # not a recognized command


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

        # Handle slash commands
        if text.startswith("/"):
            result = _handle_slash(text, engine)
            if result == "EXIT":
                break
            if result:
                continue
            # Unrecognized slash command
            print(f"  {C.RED}Unknown command: {text.split()[0]}. Type /help{C.RESET}")
            continue

        try:
            engine.chat(text)
        except KeyboardInterrupt:
            # Keep terminal session alive and avoid crashing back to GUI in a bad state.
            print(f"\n{C.YELLOW}  [Interrupted]{C.RESET}")
            engine.save_conversation()

    engine.save_conversation()
    print(f"\n{C.CYAN}  Session saved. Goodbye.{C.RESET}\n")


if __name__ == "__main__":
    main()
