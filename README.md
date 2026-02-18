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

![Version](https://img.shields.io/badge/Version-2.0%20Agentic-cyan?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Beta-orange?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)

**VoxAI IDE** is a local-first autonomous coding agent — a direct competitor to Cursor and Claude Code. It is purpose-built for the "vibe coder" who directs high-level intent and lets a specialized AI handle implementation, debugging, and execution.

---

## Why VoxAI

Standard AI editors suggest code; **VoxAI builds software**.

- **Local & Private** — Full support for local LLMs (GGUF format). Run 100% offline with zero data leakage.
- **22 Agent Tools** — File I/O, shell execution, git operations, web search, RAG memory, and codebase indexing. All available as structured XML tool calls.
- **Self-Healing Loop** — When code fails, VoxAI captures stderr, analyzes the traceback, and patches itself in a continuous loop until the task is complete.
- **Terminal Mode** — Minimize the GUI to tray and work from a Claude Code-style CLI with full tool access, streaming responses, and ASCII art.
- **Deep RAG** — A Go-based vector engine provides sub-millisecond semantic retrieval across your entire codebase and conversation history.
- **Thought Transparency** — Every tool call, file read, and command is visualized inline. You see the AI's reasoning as it happens.

---

## Features

### Agent Tools (22)

| Category | Tools |
|:---------|:------|
| **File System** | `read_file`, `write_file`, `edit_file`, `list_files`, `move_file`, `copy_file`, `delete_file`, `search_files`, `get_file_structure` |
| **Shell** | `execute_command` |
| **Git** | `git_status`, `git_diff`, `git_log`, `git_commit`, `git_push`, `git_pull`, `git_fetch` |
| **Web** | `web_search` (DuckDuckGo), `fetch_url` |
| **Memory** | `search_memory`, `search_codebase`, `index_codebase` |

### IDE

- **Tabbed Code Editor** — Syntax highlighting (Python, JS/TS, C/C++, Rust, Go, Java), line numbers, current-line highlight.
- **Find & Replace** — `Ctrl+F` opens a bar with next/prev, replace, replace all, case sensitivity.
- **Bracket Matching** — Real-time highlighting of matching `()`, `{}`, `[]` pairs with gold indicators.
- **Code Folding** — Double-click the line number gutter to collapse/expand blocks.
- **File Watcher** — Open tabs auto-reload when files change on disk (from AI tools, git, or external editors).
- **Diff Viewer** — Color-coded unified diffs in dedicated tabs. Batch multiple diffs from a single tool run.

### File Explorer

- **Git Status Indicators** — Colored dots show modified (yellow), added (green), untracked (blue), deleted (red) files.
- **Context Menus** — Right-click for: New File, New Folder, Rename, Delete, Copy Path, Copy Relative Path, Reveal in Explorer.
- **Filter Bar** — Type to filter files by name in real-time.

### Chat Panel

- **@-mention Context** — Type `@filename.py` in the input to auto-attach file contents as context.
- **Attachments** — Attach images (multimodal) or text files via the paperclip button.
- **Copy / Regenerate** — Every message has a "Copy" button. AI messages have "Regenerate" to re-run.
- **Apply / Reject Workflow** — Proposed file changes show a diff preview and require approval (unless auto-approve is enabled or Siege Mode is active).
- **Thought Blocks** — AI reasoning is shown in collapsible panels, stripped from the visible response.
- **Token Usage** — Per-message token counts in the footer. Running total in the status bar.

### Command & Control

- **Phased Mode (Default)** — The AI drafts a plan, executes one phase at a time, and waits for authorization between phases.
- **Siege Mode** — Full autonomous execution. The AI iterates up to 25 tool cycles without stopping.
- **Command Palette** — `Ctrl+Shift+P` opens a searchable action launcher with all IDE commands.

### Terminal Mode

Press the **Terminal** button in the toolbar (or use the Command Palette) to:

1. Minimize the GUI to the Windows system tray.
2. Open a new console window with a Claude Code-style CLI.
3. Full streaming AI responses with ANSI color, tool execution, and slash commands.
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
| `/status` | Show git status |
| `/export <file>` | Export conversation to markdown |

### Desktop Notifications

Windows toast notifications fire when the app is not focused:
- AI response complete
- Approval needed for destructive actions
- Phase gate reached

### Settings

- **Provider Configuration** — API keys for OpenAI, Anthropic, Google, OpenRouter, DeepSeek, Mistral, XAI.
- **Model Manager** — Scan, import, and inspect local GGUF models with VRAM compatibility estimates.
- **RAG Tuning** — Enable/disable, top-k results, minimum similarity score.
- **Agent Behavior** — Max history tokens, auto-approve writes, auto-save conversations, web search toggle.
- **Appearance** — Customizable user and AI chat colors.

### Status Bar

- Git branch name (auto-refreshes)
- Cursor position (Ln / Col)
- File encoding
- Running token count

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
│   ├── local_embeddings.py    # GGUF embedding engine
│   ├── settings.py            # QSettings-based persistence
│   ├── runner.py              # Script execution (cross-platform)
│   └── hardware.py            # GPU/CPU detection
├── ui/                        # PySide6 GUI
│   ├── main_window.py         # Main window, toolbar, menus, tray
│   ├── chat_panel.py          # Chat interface, AI/tool workers
│   ├── editor_panel.py        # Tabbed editor, find/replace, folding
│   ├── file_tree_panel.py     # Explorer with git status & context menus
│   ├── settings_dialog.py     # Settings UI
│   ├── model_manager.py       # GGUF model manager dialog
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
│   ├── search_engine/         # HNSW index, mmap storage, HTTP API
│   └── drivers/               # llama.cpp shared libraries
├── tests/                     # Test suite
├── models/llm/                # Drop GGUF files here
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

### Prerequisites

- Python 3.10+
- Git
- (Optional) NVIDIA GPU for local GGUF inference

### Install

```bash
git clone https://github.com/YourUser/VoxAI_IDE.git
cd VoxAI_IDE
pip install -r requirements.txt
```

### Configure Models

**Option A — Local Models (Private & Offline)**

1. Download a `.gguf` model (Llama 3, Mistral, Gemma, etc.).
2. Place it in `models/llm/`.
3. Select it from the model dropdown in Settings.

**Option B — Cloud Providers**

```bash
cp keys/secrets.template.json keys/secrets.json
# Edit secrets.json with your API keys
```

Supported: OpenAI, Anthropic, Google, OpenRouter, DeepSeek, Mistral, XAI.

### Run

```bash
python main.py
```

Or on Windows:

```powershell
./start_IDE.bat
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|:---------|:-------|
| `Ctrl+Shift+P` | Command Palette |
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
3. **Report** — Summarizes results and **stops**.
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

## License

See [LICENSE](LICENSE) for details.

---

**VoxAI** — *The Command Center for Autonomous Development*
