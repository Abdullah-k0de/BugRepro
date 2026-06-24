# BugRepro Sentinel: Verified AI Bug Fixing Agent

BugRepro Sentinel is an autonomous DevSecOps agent system built on Google's **Agent Development Kit (ADK 2.0)**. Its objective is to help volunteer maintainers of public-good open-source Python projects by automatically triaging, reproducing, patching, and verifying bug fixes inside a secure, fully sandboxed Docker container (no host mounts).

All operations (cloning, dependency installation, running command lines, writing files, and running test suites) run entirely within an isolated Docker container workspace with zero host filesystem mounts to ensure absolute isolation from untrusted repository code.

---

## 🚀 Multi-Stage Roadmap

1. **Stage 1 (Completed)**: Core BugRepro Sentinel Agents, Sandbox Tools, and CLI runner.
   * **Step 1**: Project Setup & Scaffolding `[COMPLETED]`
   * **Step 2**: Sandbox Engine Development (`sandbox.py`) `[COMPLETED]`
   * **Step 3**: Core Tools Implementation (`tools.py`) `[COMPLETED]`
   * **Step 4**: Agent Graph Orchestration (`agent.py`) `[COMPLETED]`
   * **Step 5**: Demo Verification `[COMPLETED]` (Successfully validated E2E against issue #2081)
2. **Stage 2 (Completed)**: Web Frontend & Backend API Server (FastAPI hosting the ADK runner).
   * **Step 1**: Backend API Architecture (FastAPI endpoints `/run`, `/run_sse`, `/sessions`, `/feedback`) `[COMPLETED]`
   * **Step 2**: Session & Artifact Persistence (state recovery and report file export) `[COMPLETED]`
   * **Step 3**: Web Frontend Design (Harmonious HSL light/dark mode, Outfit typography, two-pane UI layout) `[COMPLETED]`
   * **Step 4**: Real-time SSE Terminal Viewer (Streaming live agent console outputs and retry logs) `[COMPLETED]`
   * **Step 5**: Interactive Report Panel (Visual triage state, test logs, and syntax-highlighted git diffs) `[COMPLETED]`
3. **Stage 3**: Cloud Deployment (Deploying Backend & Frontend to Cloud).
4. **Stage 4**: Multi-repo & Node.js Support.

---

## 🏗️ Stage 1 Architecture

BugRepro Sentinel utilizes a directed state graph managed by the ADK 2.0 Workflows API. State is shared via a schema-validated Pydantic model (`BugReproState`) passed between 5 coordinated agents:

```mermaid
graph TD
  START --> issue_triage
  issue_triage -- "Reproducible/Maybe" --> repo_setup
  issue_triage -- "Not Reproducible/Out of Scope" --> evidence_report
  repo_setup --> reproduction
  reproduction --> patch_architect
  patch_architect --> verification_testing
  verification_testing -- "tests pass" --> evidence_report
  verification_testing -- "tests fail AND attempt < 3" --> patch_architect
  verification_testing -- "tests fail AND attempt >= 3" --> evidence_report
```

1. **`issue_triage`**: Uses an LLM to parse the GitHub issue URL and determine if it is reproducible/in-scope. Extracts error stack traces and CLI keywords.
2. **`repo_setup`**: Launches the Python Docker container and clones the repository directly into `/workspace` inside the container.
3. **`reproduction`**: Writes a standalone reproduction test case (`test_repro.py`) inside the container and confirms it fails (exit code != 0).
4. **`patch_architect`**: Scans the directory using tools, reads files mentioned in the traceback, proposes a minimal fix, and overwrites the files inside the container.
5. **`verification_testing`**: Runs `pytest test_repro.py` and the project test suite inside the container. If tests fail, it loops back up to 3 times to find alternative fixes.
6. **`evidence_report`**: Compiles the final report formatted as a **Maintainer-Ready GitHub Comment** (with diff and community impact section). Copies the report and the generated `.patch` file out of the container to the host `artifacts/` folder, and yields it as an event.

---

## 🔒 Security Boundary Policy

To prevent arbitrary code execution (like malicious pre/post-install hooks or test scripts) from affecting the developer's machine:

* **Zero Host Mounts**: No folders on the host are mounted to the container. Git clones, builds, and test runs are kept strictly inside the container's isolated virtual filesystem.
* **Blank Environments**: Host-level environment variables (including Google API keys and GitHub tokens) are never leaked to the sandbox container.
* **Command Sanitization**: Execution commands are passed as strict argument lists (e.g. `["pip", "install", "-r", "requirements.txt"]`) bypassing shell expansion. String commands are checked programmatically to block chaining (`&&`, `;`, `|`).
* **Regex Input Validation**: Target file edits and paths are validated in Python, preventing prompt-injected writes.

---

## 📦 Current Status: Stage 1 Completed (E2E Verified)

* **Step 1 (Scaffolding & Setup)** `[COMPLETED]`: Scaffolded ADK project under `bugrepro-agent/`.
* **Step 2 (Sandbox Engine)** `[COMPLETED]`: Developed isolated `DockerSandbox` in `sandbox.py` and passed lifecycle tests.
* **Step 3 (Core Tools)** `[COMPLETED]`: Developed custom tools in `tools.py` for issue fetching, sandbox execution, reading/writing, and patching files, passing unit tests.
* **Step 4 (Agent Orchestration)** `[COMPLETED]`: Transitioned from static sequential agent to an ADK 2.0 graph-based `Workflow` coordinating triage, setup, reproduction, patch, and verification nodes via a dynamic `run_sentinel` orchestrator.
* **Step 5 (Demo Verification)** `[COMPLETED]`: Ran E2E verification successfully targeting GitHub issue [#2081](https://github.com/google/adk-samples/issues/2081). The system triaged the issue, cloned the repo, successfully reproduced the bug with targeted tests, applied a patch, verified it on attempt 2 (learning from attempt 1's memory), generated a unified git diff block, and auto-cleaned the sandbox.

---

## 🛠️ Local Development (Stage 2)

Prerequisites:
* Python 3.11+
* Docker running on the host system
* `uv` installed (`pip install uv`)
* Node.js 18+ and `npm` installed

### 1. Setup Backend API Server
1. Navigate to the agent folder and sync dependencies:
   ```bash
   cd bugrepro-agent
   uv sync
   ```
2. Start the FastAPI development server:
   ```bash
   uv run uvicorn app.fast_api_app:app --host 127.0.0.1 --port 8000
   ```

### 2. Setup Frontend Web Client
1. Navigate to the frontend folder and install dependencies:
   ```bash
   cd ../bugrepro-frontend
   npm install
   ```
2. Start the Vite React development server:
   ```bash
   npm run dev
   ```
3. Open `http://localhost:5173` in your browser and enter a GitHub issue link (e.g. `https://github.com/google/adk-samples/issues/2081` or your playground repository link) to run Sentinel!
