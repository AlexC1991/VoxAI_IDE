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

![Version](https://img.shields.io/badge/Version-1.5%20Agentic-cyan?style=for-the-badge) ![Status](https://img.shields.io/badge/Status-Beta-orange?style=for-the-badge) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=for-the-badge)

**VoxAI IDE** is not just an editor; it's a **local-first autonomous execution core**. It is purpose-built for the "vibe coder"—the developer who directs high-level architectural intent and lets a specialized AI agent handle the heavy lifting of implementation, debugging, and terminal-level execution.

---

## � Why VoxAI? (The Vibe-Coder Advantage)

Standard AI editors suggest code; **VoxAI builds software**.

- **🛠️ Zero-Context Implementation**: With Deep RAG integration, VoxAI understands your entire project better than you do. It searches your local codebase, cross-references logic, and generates code that actually *fits*.
- **⚡ The self-Healing Loop**: When code fails, VoxAI doesn't just show an error. It captures `stderr`, analyzes the traceback, and **patches itself** in a continuous loop until the task is complete. 
- **�️ Native Terminal Authority**: The agent has full access to your local shell. It can install dependencies, migrate databases, and run test suites natively on your machine, not in a sandbox.
- **🧠 Thought Transparency**: Every tool call, file read, and command execution is visualized. You see the AI's "Thought" process as it happens, allowing for precise steering.

---

## 🏗️ Technical Deep-Dive

### 🧠 Agentic Core & RAG
- **Semantic Memory**: Uses `llama-cpp-python` to generate local vector embeddings of your files. A high-speed Go-based search engine provides sub-millisecond similarity retrieval.
- **XML Tool Protocol**: Uses a strict, low-latency XML messaging protocol to control the filesystem. This minimizes "hallucination" by forcing the AI to use structured commands for all actions.
- **Multimodal Context**: Injects image payloads directly into the LLM context window, enabling visual debugging of UI components and architectural diagrams.

### 🚀 Performance Architecture
- **Multi-Threaded Execution**: Separate threads for AI inference, tool execution, and UI rendering ensure zero-lag operation, even during heavy file indexing.
- **Subprocess Streaming**: Real-time pipe buffering allows the IDE to capture and stream `stdout/stderr` character-by-character, simulating a high-speed terminal experience.

---

## ⚖ Comparison: Agentic vs. Standard AI

| Feature | VoxAI (Agentic IDE) | Traditional AI Editors |
| :--- | :--- | :--- |
| **Logic Loop** | ✅ Self-Heals (Error -> Feedback) | ❌ Manual Copy-Paste |
| **Execution** | ✅ Native Shell / Subprocess | ❌ Suggestion Only |
| **Memory** | ✅ Full-Project RAG Context | ⚠️ File-by-File / Limited |
| **Workflow** | ✅ Directed Intent | ⚠️ Line-by-Line Autocomplete |
| **UI** | ✅ Focused Agentic View | ❌ Standard Multi-Pane |

---

## �️ Command & Control (Governance)

VoxAI is powerful by default, but you hold the keys. The system operates in two distinct modes depending on your risk tolerance and project maturity.

### 🛑 Mode 1: Phased Strategic Alignment (Default)
The AI doesn't just start hacking; it acts as a Senior Architect first.
1.  **Draft:** The AI analyzes the request and presents a **Phased Execution Plan** (e.g., *Phase 1: Dependency Install*, *Phase 2: Database Migration*, *Phase 3: Controller Logic*).
2.  **Authorize:** You review the plan. The AI **pauses** at the start of each phase.
3.  **Execute:** You grant specific authorization (`[Y/n]`) to proceed. The AI executes that phase and reports back.

### 🔥 Mode 2: "Siege Mode" (Full Auto)
For when you need speed and trust the machine.
* **The Protocol:** You explicitly authorize the agent to **"Go Limitless."**
* **The Result:** The AI bypasses all phase-gates. It will iterate, debug, patch, and execute continuously until the objective is met.
* **The Sandbox (Safety Lock):** 
    * **Write Access:** Strictly confined to the *Active Project Directory*. The AI cannot modify system files or other projects.
    * **Read Access:** Global. If you tell the AI *"Make it like ../other_project"*, it can read that external directory for context, but it can never change it.
* *Warning: Autonomous execution active. Rapid file mutations will occur within the project root.*

---

## �📦 Getting Started

1.  **Initialize Environment**
    ```powershell
    ./setup_integration.bat
    ```

2.  **Add Secrets**
    ```powershell
    # Supports OpenAI, Anthropic, Gemini, DeepSeek & Ollama
    cp keys/secrets.template.json keys/secrets.json
    ```

3.  **Boot System**
    ```powershell
    ./start_IDE.bat
    ```

---

**VoxAI** • *The Command Center for Autonomous Development*
