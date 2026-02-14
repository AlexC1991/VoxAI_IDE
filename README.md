# VoxAI Coding Agent IDE

```
██╗   ██╗ ██████╗       █████╗ ██╗    ██╗██████╗ ███████╗
██║   ██║██╔═══██╗      ██╔══██╗██║    ██║██╔══██╗██╔════╝
██║   ██║██║   ██║█████╗███████║██║    ██║██║  ██║█████╗  
╚██╗ ██╔╝██║   ██║╚════╝██╔══██║██║    ██║██║  ██║██╔══╝  
 ╚████╔╝ ╚██████╔╝      ██║  ██║██║    ██║██████╔╝███████╗
  ╚═══╝   ╚═════╝       ╚═╝  ╚═╝╚═╝    ╚═╝╚═════╝ ╚══════╝
```

---

![Version](https://img.shields.io/badge/Version-1.1%20Review-blue?style=flat-square) ![Status](https://img.shields.io/badge/Status-Beta-orange?style=flat-square) ![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20Mac-lightgrey?style=flat-square) ![Python](https://img.shields.io/badge/Python-3.10%2B-green?style=flat-square)

## 🎯 What This Is (And Isn’t)

**This is:**
- A **local-first** autonomous coding agent.
- A **real execution environment** (subprocess, not sandboxed).
- A **developer-controlled** AI workflow loop.

**This is not:**
- A browser-based coding chatbot.
- A cloud-only dev agent.
- A locked-down virtual container.

The **Coding Agent IDE** integrates into the VoxAI Orchestrator as an intelligent pair programmer. You direct intent, and the AI handles implementation, debugging, and execution on your local machine.

---

## 🏗️ Core Philosophy

**Director & Engineer Workflow**
Instead of abstract "AI coding," this IDE enforces a strict role division:
1.  **You (The Director)**: Define the high-level goal (e.g., *"Create a fast API for user login"*).
2.  **AI (The Engineer)**: Writes the code, handles imports, and structures the project.
3.  **System**: Runs the code natively on your machine.
4.  **Feedback Loop**: If it breaks, the error output is automatically fed back to the AI for immediate patching.

---

## � Example Workflow

**Prompt:** *"Build a small Flask API with user login and SQLite storage."*

1.  **Step 1 — AI Generates**:
    - `main.py`
    - `models.py`
    - `requirements.txt`
2.  **Step 2 — You Press Run**:
    - Script executes locally via subprocess.
    - **Debug Drawer** slides open automatically.
3.  **Step 3 — Error Appears**:
    - *Error: Missing dependency 'flask_sqlalchemy'.*
    - `stderr` is auto-fed back to the agent.
4.  **Step 4 — AI Patches**:
    - Updates `requirements.txt`.
    - Refactors imports.
5.  **Step 5 — Run Again**:
    - **Exit Code 0**.
    - Debug Drawer retracts.

*Result:* A working local API project in under 2 minutes.

---

## 🔒 Safety & Scope

- **Project Scoped**: The agent operates **only** inside the user-selected project directory.
- **No Hidden Execution**: All commands are visible in the Debug Drawer.
- **Manual Override**: You retain full control to edit files or stop processes at any time.
- **Local First**: Your code stays on your machine (unless using a cloud LLM provider).

---

## 🖥️ Workspace Layout

**Three-Pane Coding Deck**:

1.  **Coding Agent (Left Panel)**:
    - **Thought Process**: Hidden by default. Expand to see the AI's reasoning plan before it acts.
    - **Progress Updates**: Tracks file creation/edits in real-time.
2.  **Script Viewer (Top Right)**:
    - Real-time syntax-highlighted editor.
    - Dynamic tabs for multi-file projects.
3.  **Directory Tree (Bottom Right)**:
    - Live view of your project sandbox.
4.  **Debug Drawer (Slide-Over)**:
    - Slides in during execution.
    - Auto-retracts on success.
    - Staying open on error for debugging.

---

## 🚀 Execution Model

> **Native Subprocess Execution**

The IDE executes code directly on your host machine using your installed runtimes.
- **No Docker Overhead**: Uses your system's Python/Node/Go.
- **Live Streams**: `stdout` and `stderr` stream directly to the Debug Drawer.
- **Signal Control**: Stop button sends `SIGTERM` to the process tree.

---

## ⚖ Why Use This Instead of a Standard AI Editor?

| Feature | VoxAI Coding Agent IDE | Typical AI Code Tool |
| :--- | :--- | :--- |
| **Local Execution** | ✅ Native (Subprocess) | ❌ Often Sandboxed/Cloud |
| **Self-Healing Loop** | ✅ Built-in (Error -> Fix) | ❌ Manual Copy-Paste |
| **Directory Scope** | ✅ Explicit Project Sandbox | ⚠️ Varies |
| **Manual Override** | ✅ Full Editor Control | ⚠️ Partial / Diff Only |
| **Model Flexibility** | ✅ Cloud + Local (Ollama) | ❌ Often Cloud-Only |

---

## 📦 Installation & Setup

1.  **Install Dependencies**
    ```bat
    setup_integration.bat
    ```

2.  **Configure Secrets**
    ```bat
    copy keys\secrets.template.json keys\secrets.json
    notepad keys\secrets.json
    ```

3.  **Launch**
    ```bat
    start_IDE.bat
    ```

---

**VoxAI Orchestrator** • *Building the future of Autonomous Coding*
