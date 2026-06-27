# BugRepro Sentinel: Verified AI Bug Fixing Agent

BugRepro Sentinel is an autonomous, language-agnostic DevSecOps agent system built on Google's **Agent Development Kit (ADK 2.0)**. Its objective is to help volunteer maintainers of public-good open-source software by automatically triaging, reproducing, patching, and verifying bug fixes across multiple language toolchains (supporting Python, Java, Rust, Go, Node.js, and C/C++) inside a secure, fully sandboxed Docker container (no host mounts).

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
3. **Stage 3 (Completed)**: Cloud Deployment (Deploying Decoupled Backend & Frontend to GCP).
   * **Step 1**: Containerize Backend API (`Dockerfile` for FastAPI server) `[COMPLETED]`
   * **Step 2**: Configure GCE VM with Docker engine access (sibling container socket-sharing) `[COMPLETED]`
   * **Step 3**: Build & push backend container to Artifact Registry using Cloud Build `[COMPLETED]`
   * **Step 4**: Deploy static Frontend to Firebase Hosting CDN `[COMPLETED]`
   * **Step 5**: Configure reverse proxy via Nginx with Let's Encrypt SSL and CORS rules `[COMPLETED]`
   * **Step 6**: Configure automated nightly sandbox cleanup and container log limits `[COMPLETED]`
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

## 📦 Stage 1 Completed (E2E Verified)

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

---

## ☁️ Stage 3 Cloud Deployment Guide

To deploy BugRepro Sentinel to production on Google Cloud Platform (GCP), the static React web frontend and the Docker-enabled backend API server are deployed separately.

### 🏗️ Production Architecture Overview

```mermaid
graph TD
  User([Developer Browser]) -->|HTTPS| Frontend[Firebase Hosting CDN]
  User -->|HTTPS/SSE| LB[Cloud Load Balancer]
  LB -->|HTTP: Port 8000| VM[GCE VM Instance / GKE Node]
  VM -->|Mounts socket| Daemon[Host Docker Daemon]
  Daemon -->|Spawns / Cleans| Sandboxes[Isolated Docker Sandboxes]
```

---

### 1. Frontend Deployment (Firebase Hosting / CDN)

The React frontend compiles into static HTML/CSS/JS assets. It is hosted on a Global CDN for optimal delivery performance.

* **Target Hosting**: **Firebase Hosting** or **Google Cloud Storage (GCS) static site hosting**
* **Deployment Steps**:
  1. Add your production API endpoint to a `.env.production` file inside `bugrepro-frontend/`:
     ```env
     VITE_API_BASE_URL=https://api.bugrepro-sentinel.yourdomain.com
     ```
  2. Build production assets:
     ```bash
     cd bugrepro-frontend
     npm run build
     ```
  3. Initialize and deploy:
     ```bash
     firebase init hosting
     firebase deploy --only hosting
     ```

---

### 2. Backend API Deployment (Google Compute Engine VM)

The backend requires a runtime environment with access to a running Docker daemon to dynamically create and destroy sandbox containers. **Google Compute Engine (GCE)** or **Google Kubernetes Engine (GKE)** is required.

#### Sibling Container Architecture (VM with Docker)

Rather than executing slow nested Docker-in-Docker processes, the backend container runs side-by-side with its sandboxes:

* **The GCE Host VM** runs the main Docker engine.
* **The Backend API Container** mounts the host VM's Docker engine socket (`-v /var/run/docker.sock:/var/run/docker.sock`).
* When an agent starts a reproduction run, it sends requests via the mounted socket to spin up a sandbox container (e.g., `bugrepro-sandbox-a1b2c3d4`) on the host VM directly.

#### Deployment Steps:

1. **Prepare Dockerfile** under `bugrepro-agent/`:

   ```dockerfile
   FROM python:3.11-slim
   RUN apt-get update && apt-get install -y docker.io curl && rm -rf /var/lib/apt/lists/*
   WORKDIR /app
   RUN pip install uv
   COPY pyproject.toml uv.lock ./
   RUN uv sync --frozen --no-dev
   COPY . .
   EXPOSE 8000
   CMD ["uv", "run", "uvicorn", "app.fast_api_app:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
2. **Build & Push to Artifact Registry using Cloud Build**:

   ```bash
   gcloud builds submit --tag us-central1-docker.pkg.dev/YOUR_PROJECT_ID/repro-registry/bugrepro-backend:latest ./bugrepro-agent
   ```
3. **Configure & Launch the VM (GCE)**:
   Launch an instance running a standard Linux image with Docker installed:

   ```bash
   gcloud compute instances create bugrepro-backend-vm \
       --zone=us-central1-a \
       --machine-type=e2-medium \
       --image-family=ubuntu-2204-lts \
       --image-project=ubuntu-os-cloud \
       --metadata=startup-script="sudo apt-get update && sudo apt-get install -y docker.io" \
       --tags=http-server,https-server
   ```
4. **Launch Backend Mounting Docker Socket**:
   SSH into your VM and run the container with host-socket mapping:

   ```bash
   docker run -d \
     --name sentinel-backend \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -p 8000:8000 \
     -e ALLOW_ORIGINS="https://bug-repro-17eb1.web.app" \
     us-central1-docker.pkg.dev/YOUR_PROJECT_ID/repro-registry/bugrepro-backend:latest
   ```

---

### 3. Automated Sandbox Container Cleanup & Fail-safes

To prevent the GCE VM from accumulating orphaned sandbox containers and running out of disk space, BugRepro Sentinel implements a multi-tiered automated cleanup system:

1. **Active Run Callback Teardown**: The ADK workflow registers a `sandbox_cleanup` callback in `agent.py`. When an execution finishes (whether it succeeds, fails, or runs into a timeout), the runner triggers `after_run_callback`, which locates the session's sandbox container, calls `sandbox.stop()`, and deletes it from the VM's Docker engine.
2. **Process Exit Garbage Collection**: Python's `atexit` module is used to register a process-level cleanup hook (`cleanup_all_sandboxes`) in `tools.py`. If the FastAPI backend server process shuts down or restarts, it automatically stops and removes any tracked running sandboxes.
3. **Fail-safe Host VM Cron**: To prune any untracked or dangling containers/caches on the GCE VM host, schedule a weekly cron job on the VM OS:
   ```bash
   0 0 * * 0 docker container prune -f && docker image prune -f
   ```

---

### 4. Networking, DNS & SSL Configuration

1. **Cloud Load Balancing**: Configure an HTTPS External Application Load Balancer to route traffic to the VM.
2. **SSL Certificate**: Assign a custom domain (e.g., `api.bugrepro-sentinel.yourdomain.com`) with a Google-managed SSL certificate.
3. **CORS**: Ensure `ALLOW_ORIGINS` on the backend VM matches the frontend domain to allow cross-origin browser requests.
