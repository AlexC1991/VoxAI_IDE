# VoxAI Coding Agent IDE: The Vibe-Coder's Powerhouse

```
██╗   ██╗ ██████╗       █████╗ ██╗    ██╗██████╗ ███████╗
██║   ██║██╔═══██╗      ██╔══██╗██║    ██║██╔══██╗██╔════╝
██║   ██║██║   ██║█████╗███████║██║    ██║██║  ██║█████╗  
╚██╗ ██╔╝██║   ██║╚════╝██╔══██║██║    ██║██║  ██║██╔══╝  
 ╚████╔╝ ╚██████╔╝      ██║  ██║██║    ██║██████╔╝███████╗
  ╚═══╝   ╚═════╝       ╚═╝  ╚═╝╚═╝    ╚═╝╚═════╝ ╚══════╝
```

---

![Version](https://img.shields.io/badge/Version-1.7%20Agentic-cyan?style=for-the-badge) ![Status](https://img.shields.io/badge/Status-Beta-orange?style=for-the-badge) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=for-the-badge)

**VoxAI IDE** is not just an editor; it's a **local-first autonomous execution core**. It is purpose-built for the "vibe coder"—the developer who directs high-level architectural intent and lets a specialized AI agent handle the heavy lifting of implementation, debugging, and terminal-level execution.

---

## ⚡ Why VoxAI? (The Vibe-Coder Advantage)

Standard AI editors suggest code; **VoxAI builds software**.

-   **🛠️ Zero-Context Implementation**: With Deep RAG integration, VoxAI understands your entire project better than you do. It searches your local codebase, cross-references logic, and generates code that actually *fits*.
-   **🔌 Local & Private**: Full support for **Local LLMs** (GGUF format). Run 100% offline with zero data leakage. Your code never leaves your machine.
-   **⚡ The Self-Healing Loop**: When code fails, VoxAI doesn't just show an error. It captures `stderr`, analyzes the traceback, and **patches itself** in a continuous loop until the task is complete.
-   **🖥️ Native Terminal Authority**: The agent has full access to your local shell. It can install dependencies, migrate databases, and run test suites natively on your machine, not in a sandbox.
-   **🧠 Thought Transparency**: Every tool call, file read, and command execution is visualized. You see the AI's "Thought" process as it happens, allowing for precise steering.

---

## 🏗️ Technical Deep-Dive

### 🧠 Agentic Core & RAG
-   **Local Inference Engine**: Powered by `llama-cpp-python` for high-performance GGUF inference on CPU/GPU.
-   **Semantic Memory**: A high-speed Go-based search engine provides sub-millisecond similarity retrieval, running entirely on `localhost`.
-   **XML Tool Protocol**: Uses a strict, low-latency XML messaging protocol to control the filesystem. This minimizes "hallucination" by forcing the AI to use structured commands for all actions.
-   **Multimodal Context**: Injects image payloads directly into the LLM context window, enabling visual debugging of UI components and architectural diagrams.

### 🚀 Performance Architecture
-   **Multi-Threaded Execution**: Separate threads for AI inference, tool execution, and UI rendering ensure zero-lag operation using `PySide6`.
-   **Subprocess Streaming**: Real-time pipe buffering allows the IDE to capture and stream `stdout/stderr` character-by-character, simulating a high-speed terminal experience.

---

## ⚖ Comparison: Agentic vs. Standard AI

| Feature | VoxAI (Agentic IDE) | Traditional AI Editors |
| :--- | :--- | :--- |
| **Privacy** | ✅ **100% Local / Offline Capable** | ❌ Cloud Only |
| **Logic Loop** | ✅ **Self-Heals (Error -> Feedback)** | ❌ Manual Copy-Paste |
| **Execution** | ✅ **Native Shell / Subprocess** | ❌ Suggestion Only |
| **Memory** | ✅ **Full-Project RAG Context** | ⚠️ File-by-File / Limited |
| **Workflow** | ✅ **Directed Intent** | ⚠️ Line-by-Line Autocomplete |
| **UI** | ✅ **Focused Agentic View** | ❌ Standard Multi-Pane |

---

## 🛡️ Command & Control (Governance)

VoxAI is powerful by default, but you hold the keys. The system operates in two distinct modes depending on your risk tolerance and project maturity.

### 🛑 Mode 1: Phased Strategic Alignment (Default)
The AI doesn't just start hacking; it acts as a Senior Architect first.
1.  **Draft:** The AI analyzes the request and presents a **Phased Execution Plan** (e.g., *Phase 1: Dependency Install*, *Phase 2: Database Migration*, *Phase 3: Controller Logic*).
2.  **Authorize:** You review the plan. The AI **pauses** at the start of each phase.
3.  **Execute:** You grant specific authorization (`[Y/n]`) to proceed. The AI executes that phase and reports back.

### 🔥 Mode 2: "Siege Mode" (Full Auto)
For when you need speed and trust the machine.
*   **The Protocol:** You explicitly authorize the agent to **"Go Limitless."**
*   **The Result:** The AI bypasses all phase-gates. It will iterate, debug, patch, and execute continuously until the objective is met.
*   **The Sandbox (Safety Lock):** 
    *   **Write Access:** Strictly confined to the *Active Project Directory*. The AI cannot modify system files or other projects.
    *   **Read Access:** Global. If you tell the AI *"Make it like ../other_project"*, it can read that external directory for context, but it can never change it.

---

## 📦 Getting Started

### 1. Initialize Environment
```powershell
./setup_integration.bat
```

### 2. Configure Models

#### ⚡ Option A: Local Models (Private & Offline)
VoxAI has a **native GGUF inference engine**. You do NOT need Ollama or external servers.
1.  **Download** a `.gguf` model (e.g., *Llama-3-8B-Instruct*, *Mistral-7B*, *Gemma*).
2.  **Drop** the file into the `models/llm/` directory.
3.  **Select** it from the "providers" dropdown in Settings.

*Note: Performance depends on your hardware (CPU/GPU).*

#### 🌐 Option B: Cloud Providers (High Performance)
For complex tasks, connect to industry-standard APIs:
-   **OpenAI** (GPT-4o, GPT-4-Turbo)
-   **Anthropic** (Claude 3.5 Sonnet, Opus)
-   **Google** (Gemini 1.5 Pro/Flash)
-   **OpenRouter** (DeepSeek, Qwen, and 100+ others via one key)

To enable:
```powershell
cp keys/secrets.template.json keys/secrets.json
# Edit keys/secrets.json with your API keys
```

### 3. Boot System
```powershell
./start_IDE.bat
```

---

**VoxAI** • *The Command Center for Autonomous Development*
