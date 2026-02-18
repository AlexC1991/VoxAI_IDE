# VoxAI Coding Agent IDE

```
 ██╗   ██╗ ██████╗ ██╗  ██╗ █████╗ ██╗
 ██║   ██║██╔═══██╗╚██╗██╔╝██╔══██╗██║
 ██║   ██║██║   ██║ ╚███╔╝ ███████║██║
 ╚██╗ ██╔╝██║   ██║ ██╔██╗ ██╔══██║██║
  ╚████╔╝ ╚██████╔╝██╔╝ ██╗██║  ██║██║
   ╚═══╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝
```

---

![Version](https://img.shields.io/badge/Version-2.1%20Agentic-cyan?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Beta-orange?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)
![Build](https://img.shields.io/github/actions/workflow/status/BattyBatterson/VoxAI_IDE/build.yml?style=for-the-badge&label=Build)

**VoxAI IDE** is a local-first autonomous coding agent — built to compete with Cursor and Claude Code. Purpose-built for developers who direct high-level intent and let a specialized AI handle implementation, debugging, and execution end-to-end.

> Download the latest Windows release from the [Releases](https://github.com/BattyBatterson/VoxAI_IDE/releases) page — no Python install required.

---

## Why VoxAI

Standard AI editors suggest code; **VoxAI builds software**.

- **Local & Private** — Full support for local LLMs (GGUF format). Run 100% offline with zero data leakage.
- **22 Agent Tools** — File I/O, shell execution, git operations, web search, RAG memory, and codebase indexing — all via structured XML tool calls.
- **Self-Healing Loop** — When code fails, VoxAI captures stderr, analyzes the traceback, and patches itself in a continuous loop until the task is complete.
- **Terminal Mode** — Minimize the GUI to tray and work from a Claude Code-style CLI with full tool access, streaming responses, and slash commands.
- **Deep RAG** — A Go-based vector engine (HNSW + mmap) provides sub-millisecond semantic retrieval across your entire codebase and conversation history.
- **Thought Transparency** — Every tool call, file read, and command is visualized inline. You see the AI's reasoning as it happens.
- **Token Optimization** — Automatic truncation, history compression, and system prompt condensing. ~30-50% fewer tokens per request.

---

## Features

### Agent Tools (22)

| Category | Tools |
|:---------|:------|
| **File System** | `read_file`, `write_file`, `edit_file`, `list_files`, `move_file`, `copy_file`, `delete_file`, `search_files`, `get_file_structure` |
| **Shell** | `execute_command` |
| **Git** | `git_status`, `git_diff`, `git_log`, `git_commit`, `git_push`, `git_pull`, `git_fetch` |
| **Web** | `web_search` (DuckDuckGo via IronGate), `fetch_url` |
| **Memory** | `search_memory`, `search_codebase`, `index_codebase` |

### Chat & AI

- **Auto-Context** — The open file, cursor position, and surrounding code are automatically attached to every message.
- **@-mention Context** — Type `@filename.py` in the input to attach file contents.
- **Conversation History** — `Ctrl+H` opens a sidebar listing all saved conversations. Click to switch, create, or delete sessions.
- **Attachments** — Attach images (multimodal) or text files via the `+` button.
- **Copy / Regenerate** — Every message has Copy; AI messages have Regenerate.
- **Apply / Reject** — Proposed file changes show a diff preview and require approval (unless auto-approve or Siege Mode).
- **Collapsible Thinking** — AI reasoning is shown in expandable panels, stripped from the visible response.
- **Tool Result Folding** — Tool outputs appear as one-line collapsible summaries to keep the chat clean.
- **Token Footer** — Per-message token breakdown: `tokens: total (in: prompt · out: completion)`.
- **Context Window Bar** — Color-coded fill in the status bar (green/yellow/red).
- **Model & Mode Selectors** — Inline in the input bar, Cursor-style. Switch models or modes without leaving the chat.

### Code Editor

- **Tabbed Editor** — Syntax highlighting for Python, JS/TS, C/C++, Rust, Go, Java. Line numbers, current-line highlight.
- **Find & Replace** — `Ctrl+F` with next/prev, replace, replace all, case sensitivity.
- **Bracket Matching** — Real-time highlighting of matching `()`, `{}`, `[]` pairs.
- **Code Folding** — Double-click the gutter to collapse/expand blocks.
- **File Watcher** — Open tabs auto-reload when files change on disk.
- **Live Change Highlighting** — When the AI writes a file, changed lines highlight green and removed lines highlight red using `difflib`.
- **Diff Viewer** — Color-coded unified diffs in dedicated tabs.
- **Code Outline** — `Ctrl+Shift+L` shows classes, functions, and methods for the active file (AST for Python, regex for others).

### File Explorer

- **Git Status Indicators** — Colored dots: modified (yellow), added (green), untracked (blue), deleted (red).
- **Git Diff** — Right-click any changed file to view a full color-coded diff.
- **Context Menus** — New File, New Folder, Rename, Delete, Copy Path, Copy Relative Path, Reveal in Explorer, Show Git Diff.
- **Filter Bar** — Type to filter files by name in real-time.

### Project Search

- **Project-Wide Search** — `Ctrl+Shift+F` opens grep-style search across all project files with regex, case-sensitivity, and file-type filters.
- **Quick File Switcher** — `Ctrl+P` opens a fuzzy-search overlay to jump to any file by name instantly.

### Command & Control

| Mode | Behavior |
|:-----|:---------|
| **Phased (Default)** | Executes one phase at a time. Reports results and waits for authorization. |
| **Siege (Full Auto)** | Iterates up to 25 tool cycles without stopping. Self-heals on errors. |

- **Command Palette** — `Ctrl+Shift+P` opens a searchable action launcher with all IDE commands.

### Terminal Mode

Press the Terminal icon in the top bar (or use the Command Palette) to:

1. Minimize the GUI to the Windows system tray.
2. Open a new console window with a Claude Code-style CLI.
3. Stream AI responses with ANSI color, tool execution, and slash commands.
4. Conversation history carries over from the GUI session.
5. Double-click the tray icon or type `/exit` to return to the GUI.

**Slash commands:**

| Command | Description |
|:--------|:------------|
| `/help` | Show all commands |
| `/exit` | Quit terminal, return to GUI |
| `/clear` | Clear conversation context |
| `/mode` | Toggle Phased / Siege |
| `/model` | Show current model |
| `/model <name>` | Switch to a different model |
| `/models` | List all enabled models |
| `/tokens` | Show conversation token estimate |
| `/status` | git status |
| `/branch` | Show current branch |
| `/branches` | List all branches |
| `/log [n]` | git log (default 10) |
| `/diff [file]` | git diff |
| `/commit <msg>` | Stage all + commit |
| `/push [remote] [branch]` | git push |
| `/pull [remote] [branch]` | git pull |
| `/fetch [remote]` | git fetch |
| `/stash` / `/stash pop` | Stash management |
| `/checkout <branch>` | Switch branch |
| `/files [path]` | List project files |
| `/search <query>` | Search across files |
| `/run <command>` | Execute a shell command |
| `/index` | Re-index project for RAG |
| `/export <file>` | Export conversation to markdown |

### Desktop Notifications

Windows toast notifications fire when the app is not focused:
- AI response complete
- Approval needed for destructive actions
- Phase gate reached

### Settings (Tabbed)

| Tab | Contents |
|:----|:---------|
| **Providers & Models** | API keys for OpenAI, Anthropic, Google, OpenRouter, DeepSeek, Mistral, XAI. GGUF model manager with VRAM estimates. |
| **Agent & RAG** | Max history tokens, auto-approve, auto-save, web search toggle. RAG enable/disable, top-k, similarity threshold. |
| **Appearance** | Customizable user and AI chat colors. |

### Status Bar

- Git branch name (auto-refreshes)
- Cursor position (Ln / Col)
- File encoding
- Token usage progress bar (color-coded)

---

## Architecture

```
VoxAI_IDE/
├── main.py                    # Entry point
├── core/                      # Backend
│   ├── ai_client.py           # Multi-provider AI client (streaming)
│   ├── agent_tools.py         # 22 tool implementations
│   ├── code_parser.py         # XML tool call parser
│   ├── prompts.py             # System prompts & mode injection
│   ├── rag_client.py          # Vector search client (Go backend)
│   ├── indexer.py             # Codebase chunker & indexer
│   ├── local_embeddings.py    # GGUF embedding engine (llama.cpp)
│   ├── settings.py            # QSettings-based persistence
│   ├── runner.py              # Script execution (cross-platform)
│   └── hardware.py            # GPU/CPU detection
├── ui/                        # PySide6 GUI
│   ├── main_window.py         # Main window, icon bar, menus, tray
│   ├── chat_panel.py          # Chat interface, AI/tool workers
│   ├── editor_panel.py        # Tabbed editor, find/replace, folding
│   ├── file_tree_panel.py     # Explorer with git status & context menus
│   ├── settings_dialog.py     # Settings UI (tabbed)
│   ├── model_manager.py       # GGUF model manager dialog
│   ├── search_panel.py        # Project-wide search
│   ├── file_switcher.py       # Quick file switcher (Ctrl+P)
│   ├── code_outline.py        # Symbol outline sidebar
│   ├── history_sidebar.py     # Conversation history browser
│   ├── syntax_highlighter.py  # Syntax highlighting engine
│   ├── debug_drawer.py        # Terminal output panel
│   ├── crash_reporter.py      # Crash dialog
│   └── widgets/
│       └── chat_items.py      # Message & progress widgets
├── cli/                       # Terminal Mode
│   └── terminal_mode.py       # Claude Code-style CLI
├── Vox_IronGate/              # Web client backend
│   ├── web_client.py          # DuckDuckGo search & URL fetch
│   └── lib/
│       ├── config.py          # Timeouts, user agents
│       └── security.py        # Rate limiting, URL safety, IP blocking
├── Vox_RIG/                   # RAG vector engine (Go)
│   ├── search_engine/         # HNSW index, mmap storage, HTTP + CLI
│   │   └── main.go            # Unified server/CLI entry point
│   └── drivers/               # llama.cpp shared libraries
├── tests/                     # Test suite
├── models/
│   ├── llm/                   # Drop GGUF chat models here
│   └── embeddings/            # Drop GGUF embedding models here
├── keys/                      # API key configuration
└── resources/                 # UI assets (icons, backgrounds)
```

### Agentic Loop

```
User Input
    │
    ▼
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  RAG Context │────▶│  LLM Stream  │────▶│  Tool Parser │
│  (retrieve)  │     │  (generate)  │     │  (XML parse) │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                         ┌───────────────────────┘
                         ▼
                  ┌─────────────┐
                  │ Tool Worker │──▶ file I/O, git, shell, web
                  │ (execute)   │
                  └──────┬──────┘
                         │
                         ▼
                  [TOOL_RESULT] ──▶ fed back to LLM ──▶ loop
```

### Threading Model

| Thread | Responsibility |
|:-------|:---------------|
| **Main (UI)** | PySide6 event loop, widget rendering, user input |
| **AIWorker** | Streams tokens from the AI provider |
| **ToolWorker** | Executes tool calls (file I/O, git, web, shell) |
| **IndexingWorker** | Background codebase indexing into RAG |
| **RAG Server** | Go subprocess — HTTP vector engine on 127.0.0.1 |

---

## Getting Started

### Option 1 — Download Release (Recommended)

1. Go to the [Releases](https://github.com/BattyBatterson/VoxAI_IDE/releases) page.
2. Download the latest `VoxAI_IDE-vX.X.X-windows.zip`.
3. Extract and run `VoxAI_IDE.exe`.
4. (Optional) Drop `.gguf` models into the `models/llm/` folder for offline use.

### Option 2 — Run from Source

**Prerequisites:** Python 3.10+, Git, (Optional) Go 1.22+ for RAG engine, NVIDIA GPU for local GGUF inference.

```bash
git clone https://github.com/BattyBatterson/VoxAI_IDE.git
cd VoxAI_IDE
pip install -r requirements.txt
python main.py
```

Or on Windows:

```powershell
.\start_IDE.bat
```

**Build the RAG engine (optional, improves performance):**

```bash
cd Vox_RIG/search_engine
go build -o vox-vector-engine.exe .
```

### Configure Models

**Local Models (Private & Offline)**

1. Download a `.gguf` model (Llama 3, Mistral, Gemma, Qwen, etc.).
2. Place it in `models/llm/`.
3. For embeddings, place `nomic-embed-text-v1.5.Q8_0.gguf` (or similar) in `models/embeddings/`.
4. Select models from the dropdown in Settings.

**Cloud Providers**

Open Settings (`Ctrl+,`) and enter API keys for any of:
OpenAI, Anthropic, Google, OpenRouter, DeepSeek, Mistral, XAI.

---

## Keyboard Shortcuts

| Shortcut | Action |
|:---------|:-------|
| `Ctrl+Shift+P` | Command Palette |
| `Ctrl+P` | Quick File Switcher |
| `Ctrl+Shift+F` | Search in Project |
| `Ctrl+Shift+L` | Code Outline |
| `Ctrl+H` | Conversation History |
| `Ctrl+B` | Toggle File Tree |
| `Ctrl+Shift+E` | Toggle Editor |
| `Ctrl+F` | Find & Replace |
| `Ctrl+S` | Save file |
| `Ctrl+O` | Open file |
| `Ctrl+Shift+O` | Open project |
| `Ctrl+,` | Settings |
| `` Ctrl+` `` | Toggle debug panel |
| `Enter` | Send message |
| `Shift+Enter` | New line in chat |
| `Escape` | Stop AI generation |
| `Ctrl+L` | Clear chat context |

---

## Command & Control Modes

### Phased Mode (Default)

The AI acts as a senior architect:

1. **Draft** — Analyzes the request, presents a phased execution plan.
2. **Execute** — Performs one phase using tools.
3. **Report** — Summarizes results in detail and **stops**.
4. **Authorize** — You review and send a message to continue.

### Siege Mode (Full Auto)

For when you trust the machine:

- The AI bypasses all phase gates.
- Iterates up to 25 tool cycles without stopping.
- Self-heals: captures errors, patches code, retries.
- Write access is strictly confined to the active project directory.

---

## Security

- **Write sandbox** — AI can only write within the active project directory.
- **Read access** — Global filesystem read for cross-project context.
- **Web safety** — IronGate blocks requests to localhost, private IPs (RFC 1918), link-local, and cloud metadata endpoints.
- **Rate limiting** — Token-bucket limiter on outbound HTTP requests (15/min).
- **Approval workflow** — Destructive actions (`delete_file`, `execute_command`, `git_commit`, `git_push`) require explicit user confirmation unless in Siege Mode or auto-approve is enabled.
- **RAG isolation** — The vector engine runs on `127.0.0.1` only. No external network access.

---

## Building from Source

To create a standalone Windows executable:

```bash
pip install pyinstaller
pyinstaller --onedir --windowed --name "VoxAI_IDE" \
  --add-data "resources;resources" \
  --add-data "cli;cli" \
  --add-data "core;core" \
  --add-data "ui;ui" \
  --add-data "Vox_IronGate;Vox_IronGate" \
  --hidden-import PySide6 \
  --hidden-import llama_cpp \
  main.py
```

Releases are also built automatically via GitHub Actions when a new tag is published.

---

## License

See [LICENSE](LICENSE) for details.

---

**VoxAI** — *The Command Center for Autonomous Development*
