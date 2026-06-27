# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import logging
import google.auth
from google.adk.agents import Agent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.workflow import Workflow, START, node
from google.adk.events.event import Event
from google.adk.agents.context import Context
from typing import Any
from google.adk.models import Gemini
from google.genai import types as genai_types
from google.adk.plugins.logging_plugin import LoggingPlugin
from google.adk.plugins.debug_logging_plugin import DebugLoggingPlugin

# Configure standard Python logging for console visibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

import sys
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from app.tools import (
    fetch_github_issue,
    clone_and_setup_repo,
    run_sandbox_command,
    read_sandbox_file,
    write_sandbox_file,
    patch_file_content,
    save_triage_decision,
    save_reproduction_results,
    save_patch_results,
    save_verification_results,
)

# GCP authentication setup for Vertex AI
_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# Common LLM configuration
model_name = "gemini-2.5-flash"
cfg = genai_types.GenerateContentConfig(temperature=0.1)

# 1. Issue Triage Agent
issue_triage_agent = Agent(
    name="issue_triage_agent",
    model=Gemini(model=model_name),
    generate_content_config=cfg,
    instruction=(
        "You are the Issue Triage Agent.\n"
        "Your task is to analyze the GitHub issue URL provided in the user's message.\n"
        "1. Call the `fetch_github_issue` tool using the user's provided issue URL.\n"
        "2. Examine the retrieved issue title and body. Decide if this issue is automatically fixable.\n"
        "   To be automatically fixable (FIXABLE), the issue must meet the following MVP criteria:\n"
        "   - The repo must be a Python, Node.js/TypeScript, Go, Rust, Java, C, or C++ project.\n"
        "   - There must be a clear bug description or steps to reproduce.\n"
        "   - It must not require a database, complex external APIs, private keys, or browser/UI interaction.\n"
        "3. Call the `save_triage_decision` tool with your decision (True if FIXABLE, False otherwise) and a detailed reason.\n"
        "Finally, summarize your decision and explanation to the user."
    ),
    tools=[fetch_github_issue, save_triage_decision],
)

# 2. Repo Setup Agent
repo_setup_agent = Agent(
    name="repo_setup_agent",
    model=Gemini(model=model_name),
    generate_content_config=cfg,
    instruction=(
        "You are the Repo Setup Agent.\n"
        "Your task is to set up the repository inside the isolated Docker sandbox environment.\n"
        "1. Check the triage status in the session state. If 'triage_status' is 'NOT_FIXABLE', stop immediately and explain that setup is skipped.\n"
        "2. If the status is 'FIXABLE', read the 'repo_url' from the state, and call the `clone_and_setup_repo` tool to clone the repository and install dependencies.\n"
        "Report the setup status and the results of dependency installation to the user."
    ),
    tools=[clone_and_setup_repo],
)

# Shared Sandbox tools list to ensure all sandbox-facing agents have necessary capabilities
sandbox_tools = [
    run_sandbox_command,
    read_sandbox_file,
    write_sandbox_file,
    patch_file_content,
]

# 3. Reproduction Agent
reproduction_agent = Agent(
    name="reproduction_agent",
    model=Gemini(model=model_name),
    generate_content_config=cfg,
    instruction=(
        "You are the Reproduction Agent.\n"
        "Your task is to reproduce the reported bug inside the Docker sandbox.\n"
        "1. Check the triage status in the input or state. If 'triage_status' is 'NOT_FIXABLE', stop immediately.\n"
        "2. Read the issue details from the input. Write a reproduction test file or script using `write_sandbox_file` to trigger the bug.\n"
        "   - Write the test in the language of the repository (e.g., Python (`test_repro.py`), JavaScript/TypeScript (`repro.test.js`), Go (`repro_test.go`), Rust (`repro_test.rs`), Java (`ReproTest.java`), C/C++ (`repro_test.cpp`)).\n"
        "   - IMPORTANT: The reproduction test MUST import the functions/modules directly from the cloned repository.\n"
        "   - Only create new files for the reproduction test case itself. Do not create new source files in the repository unless it is strictly required to reproduce the bug.\n"
        "   - DO NOT copy, redefine, or hardcode the functions or their buggy implementations inside the test file, as doing so will make it impossible for subsequent patches to fix the test. The test must test the actual codebase files in the repository.\n"
        "   - IMPORTANT: The reproduction test should assert the CORRECT, EXPECTED behavior of the code. This means "
        "     the test MUST FAIL when the bug is present, and PASS only after the bug is fixed.\n"
        "3. Run the test file using `run_sandbox_command` with the appropriate command for the language.\n"
        "   - IMPORTANT (COMPILED LANGUAGES): For compiled languages like Rust, Java, and C/C++, you MUST ensure "
        "     compilation happens before test execution. Use package-manager test commands (e.g., `['cargo', 'test']` "
        "     or `['mvn', '-ntp', 'clean', 'test']`) which handle recompilation automatically (ALWAYS use the `-ntp` or `--no-transfer-progress` flag when running Maven to prevent download progress bars from polluting the output), or write a shell script to run "
        "     both compilation and execution (e.g. `g++ -o suite math.cpp repro.cpp` followed by `./suite`) and execute it.\n"
        "4. Verify that you observe the expected assertion failure or crash (proving reproduction succeeded).\n"
        "5. Call `save_reproduction_results` with: \n"
        "   - `reproduced`: True if the bug was successfully reproduced with a failing test / error, False otherwise.\n"
        "   - `failure_logs`: The test stdout/stderr showing the bug crash.\n"
        "   - `test_file_path`: The path of the reproduction test file you created or ran.\n"
        "   - `test_command`: The command used to run the reproduction test (e.g. `['cargo', 'test']` or `['mvn', 'clean', 'test']`) as a list of strings.\n"
        "Explain your findings and the test run results to the user."
    ),
    tools=sandbox_tools + [save_reproduction_results],
)

# 4. Patch Agent
patch_agent = Agent(
    name="patch_agent",
    model=Gemini(model=model_name),
    generate_content_config=cfg,
    instruction=(
        "You are the Patch Agent.\n"
        "Your task is to apply a minimal code change to fix the reproduced bug.\n"
        "1. Check the triage status and reproduction status in the input. If triage is 'NOT_FIXABLE' or reproduction is 'NOT_REPRODUCED', stop immediately.\n"
        "2. Review the previous failed attempts in the input if they exist. Propose a completely different, corrected fixing strategy; DO NOT repeat the same failed patches.\n"
        "3. Locate the source file containing the bug by analyzing the reproduction results and issue description (you can use command line tools or search repository files), and read it using `read_sandbox_file`.\n"
        "4. Apply a minimal, precise code change to fix the bug.\n"
        "   - Prefer modifying existing files by applying minimal, line-by-line edits (using the `patch_file_content` tool) to keep the git diff as concise as possible. Avoid completely overwriting the entire file contents unless the file is very small or it is necessary.\n"
        "   - Only create a new source file if it is absolutely required as part of the bug fix.\n"
        "5. Call the `save_patch_results` tool with:\n"
        "   - `patched`: True if the patch was applied, False otherwise.\n"
        "   - `patch_details`: A description of the changes made and the file path.\n"
        "Explain the applied patch to the user, highlighting how it differs from any previous failed attempts."
    ),
    tools=sandbox_tools + [save_patch_results],
)

# 5. Verification Agent
verification_agent = Agent(
    name="verification_agent",
    model=Gemini(model=model_name),
    generate_content_config=cfg,
    instruction=(
        "You are the Verification Agent.\n"
        "Your task is to verify that the patch fixed the bug and compile the final report.\n"
        "1. If 'triage_status' in the input or state is 'NOT_FIXABLE', output the final report showing that the issue is out of scope and call `save_verification_results` with passed=False and logs='Out of scope'.\n"
        "2. If 'reproduction_status' in the input or state is 'NOT_REPRODUCED', output that the bug could not be reproduced and call `save_verification_results` with passed=False and logs='Could not reproduce'.\n"
        "3. If 'reproduction_status' in the input or state is 'REPRODUCED':\n"
        "   - Retrieve the reproduction test file path from 'reproduction_test_file' and the test command from 'reproduction_test_command' in the input or state.\n"
        "   - Run the reproduction test using `run_sandbox_command` with the saved `reproduction_test_command` command.\n"
        "     IMPORTANT: If the codebase is a compiled language (Rust, Java, C/C++), make sure standard compilation is executed (or a clean rebuild is triggered) before executing the tests so that the patch changes are correctly picked up.\n"
        "   - Run `run_sandbox_command` with the arguments `['git', 'diff']` to obtain the actual unified git diff inside the sandbox.\n"
        "   - Check if the tests passed. Call `save_verification_results` with `passed=True` (if the reproduction test passes) or `passed=False` (if it fails), and pass the full stdout/stderr of the test run as the `logs` argument.\n"
        "4. Output the final 'BugRepro Sentinel Result' showing:\n"
        "   - Issue Details (URL, Title)\n"
        "   - Reproducibility status (Reproduced / Could not reproduce)\n"
        "   - Patch Applied (file changes, diff description, and the raw unified git diff output block from git diff)\n"
        "   - Verification status (Passed / Failed)\n"
        "   - Test summary (Before: failed tests vs After: passed tests)\n"
        "Present this final summary report clearly in your response."
    ),
    tools=sandbox_tools + [save_verification_results],
)

from google.adk.plugins.base_plugin import BasePlugin

class SandboxCleanupPlugin(BasePlugin):
    """Ensures the sandbox Docker container is stopped and removed, even on errors."""
    def __init__(self):
        super().__init__(name="sandbox_cleanup")

    async def after_run_callback(self, **kwargs) -> None:
        ctx = kwargs.get("callback_context") or kwargs.get("invocation_context")
        if ctx:
            state = getattr(ctx, "state", None) or getattr(getattr(ctx, "session", None), "state", None)
            if state:
                # 1. Stop sandbox using sandbox_id
                sandbox_id = state.get("sandbox_id")
                if sandbox_id:
                    from app.tools import _ACTIVE_SANDBOXES
                    sandbox = _ACTIVE_SANDBOXES.pop(sandbox_id, None)
                    if sandbox:
                        try:
                            sandbox.stop()
                        except Exception:
                            pass
                    state["sandbox_id"] = None
                
                # 2. Fallback to legacy sandbox key
                sandbox = state.get("sandbox")
                if sandbox:
                    try:
                        sandbox.stop()
                    except Exception:
                        pass
                    state["sandbox"] = None

    async def close(self) -> None:
        """Called when the Runner closes. Stop all active sandboxes."""
        from app.tools import _ACTIVE_SANDBOXES
        if _ACTIVE_SANDBOXES:
            for sandbox_id, sandbox in list(_ACTIVE_SANDBOXES.items()):
                try:
                    sandbox.stop()
                except Exception:
                    pass
            _ACTIVE_SANDBOXES.clear()

@node(rerun_on_resume=True)
async def run_sentinel(ctx: Context, node_input: Any) -> Any:
    # 1. Run Issue Triage Agent
    triage_res = await ctx.run_node(issue_triage_agent, node_input=node_input)
    
    triage_status = ctx.state.get("triage_status")
    if triage_status != "FIXABLE":
        # Out of scope: compile final report
        verify_input = f"Issue URL: {ctx.state.get('issue_url')}\nIssue Title: {ctx.state.get('issue_title')}\nTriage Status: {triage_status}\nTriage Reason: {ctx.state.get('triage_reason')}\n\nTriage Agent Response:\n{triage_res}"
        return await ctx.run_node(verification_agent, node_input=verify_input)
        
    # 2. Run Repo Setup Agent
    repo_url = ctx.state.get("repo_url")
    setup_input = f"Triage Status: {triage_status}\nTriage Reason: {ctx.state.get('triage_reason')}\nRepository URL: {repo_url}"
    setup_res = await ctx.run_node(repo_setup_agent, node_input=setup_input)
    
    # 3. Run Reproduction Agent
    issue_body = ctx.state.get("issue_body", "")
    repro_input = f"Triage Status: {triage_status}\nRepository setup result: {setup_res}\nIssue URL: {ctx.state.get('issue_url')}\nIssue Title: {ctx.state.get('issue_title')}\nIssue Description:\n{issue_body}"
    repro_res = await ctx.run_node(reproduction_agent, node_input=repro_input)
    
    reproduction_status = ctx.state.get("reproduction_status")
    if reproduction_status != "REPRODUCED":
        # Reproduction failed: compile final report
        verify_input = f"Issue URL: {ctx.state.get('issue_url')}\nIssue Title: {ctx.state.get('issue_title')}\nTriage Status: {triage_status}\nReproduction Status: {reproduction_status}\nReproduction Logs:\n{ctx.state.get('reproduction_logs')}\n\nReproduction Agent Response:\n{repro_res}"
        return await ctx.run_node(verification_agent, node_input=verify_input)

    # 4. Patch & Verification Loop (up to 3 attempts)
    attempts = 1
    ctx.state["patch_attempts"] = attempts
    
    issue_title = ctx.state.get("issue_title", "")
    patch_input = (
        f"Triage Status: {triage_status}\n"
        f"Reproduction Status: {reproduction_status}\n"
        f"Reproduction Test File: {ctx.state.get('reproduction_test_file')}\n"
        f"Reproduction Logs:\n{ctx.state.get('reproduction_logs')}\n\n"
        f"Issue URL: {ctx.state.get('issue_url')}\n"
        f"Issue Title: {issue_title}\n"
        f"Issue Description:\n{issue_body}\n\n"
        f"Reproduction Summary:\n{repro_res}\n\n"
        f"Please identify the issue in the repository files, read the relevant file, and apply a minimal, precise patch to fix it."
    )
    
    repro_test_file = ctx.state.get("reproduction_test_file")
    patch_res = ""
    while attempts <= 3:
        # Run Patch Agent
        patch_res = await ctx.run_node(patch_agent, node_input=patch_input)
        
        # Run verification commands directly inside the node to execute tests deterministically and prevent intermediate UI spam
        test_command = ctx.state.get("reproduction_test_command")
        if not test_command:
            # Fallback based on file extension
            if repro_test_file.endswith(".py"):
                test_command = ["pytest", repro_test_file]
            elif repro_test_file.endswith(".js") or repro_test_file.endswith(".ts"):
                test_command = ["node", repro_test_file]
            elif repro_test_file.endswith(".go"):
                test_command = ["go", "test", repro_test_file]
            elif repro_test_file.endswith(".rs"):
                test_command = ["cargo", "test"]
            else:
                test_command = ["pytest", repro_test_file]
        
        test_res = run_sandbox_command(test_command, tool_context=ctx)
        passed = test_res.get("exit_code") == 0
        logs = test_res.get("stdout", "")
        
        save_verification_results(passed=passed, logs=logs, tool_context=ctx)
        
        verification_status = ctx.state.get("verification_status")
        if verification_status == "PASSED" or attempts >= 3:
            break
            
        # Prepare context for next attempt
        attempts += 1
        ctx.state["patch_attempts"] = attempts
        
        failed_logs = ctx.state.get("verification_logs", "")
        failed_patch = ctx.state.get("patch_details", "")
        patch_history_str = ""
        patch_history = ctx.state.get("patch_history", [])
        if patch_history:
            patch_history_str = "\nPrevious Failed Attempts:\n" + "\n".join(
                f"Attempt {i+1}:\nPatch Details: {h['patch_details']}\nVerification Logs: {h['verification_logs']}\n"
                for i, h in enumerate(patch_history)
            )
        patch_input = (
            f"Verification failed on attempt {attempts - 1}!\n"
            f"Here is the failed patch details:\n{failed_patch}\n\n"
            f"Here is the test failure logs:\n{failed_logs}\n\n"
            f"Issue URL: {ctx.state.get('issue_url')}\n"
            f"Issue Title: {issue_title}\n"
            f"Issue Description:\n{issue_body}\n"
            f"{patch_history_str}\n"
            f"Please analyze these failures and apply a different patch. Propose a completely different fixing strategy and do NOT repeat the same failed patches."
        )
        
    # 5. Compile and stream the FINAL evidence report EXACTLY ONCE after the patch loop finishes
    verify_input = (
        f"Issue URL: {ctx.state.get('issue_url')}\n"
        f"Issue Title: {issue_title}\n"
        f"Triage Status: {triage_status}\n"
        f"Reproduction Status: {reproduction_status}\n"
        f"Patch Status: {ctx.state.get('patch_status')}\n"
        f"Patch Details: {ctx.state.get('patch_details')}\n"
        f"Reproduction Test File: {repro_test_file}\n\n"
        f"Patch Agent Response:\n{patch_res}"
    )
    return await ctx.run_node(verification_agent, node_input=verify_input)

# Root coordinator orchestrator
root_agent = Workflow(
    name="root_agent",
    edges=[
        (START, run_sentinel),
    ]
)

# App interface definition
app = App(
    root_agent=root_agent,
    name="app",
    plugins=[
        SandboxCleanupPlugin(),
        LoggingPlugin(),
        DebugLoggingPlugin(output_path="adk_debug.yaml"),
    ],
)
