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
import re
import shlex
import httpx
import atexit
import logging
from google.adk.tools import ToolContext
from app.sandbox import DockerSandbox

logger = logging.getLogger("bugrepro.sandbox")

# Global registry to store DockerSandbox instances in Python memory
# This keeps the ADK session state JSON-serializable (contains only string sandbox_id).
_ACTIVE_SANDBOXES = {}

def get_sandbox(tool_context: ToolContext) -> DockerSandbox | None:
    """Retrieves the active DockerSandbox instance from the global registry,
    reconnects if the process reloaded, or falls back to state for tests.
    """
    # 1. Retrieve using sandbox_id from state
    sandbox_id = tool_context.state.get("sandbox_id")
    if sandbox_id:
        sandbox = _ACTIVE_SANDBOXES.get(sandbox_id)
        if sandbox:
            return sandbox
        
        # Process restart/reload recovery: Re-initialize DockerSandbox using running container name
        try:
            sandbox = DockerSandbox(image="python:3.11-slim")
            sandbox.container_name = sandbox_id
            # Retrieve reference to existing container
            sandbox.container = sandbox.client.containers.get(sandbox_id)
            _ACTIVE_SANDBOXES[sandbox_id] = sandbox
            logger.info(f"Successfully reconnected to active sandbox container: {sandbox_id}")
            return sandbox
        except Exception as e:
            logger.warning(f"Could not reconnect to sandbox container '{sandbox_id}': {e}")
            
    # 2. Check for legacy sandbox object in state (fallback for tests)
    sandbox_obj = tool_context.state.get("sandbox")
    if sandbox_obj and isinstance(sandbox_obj, DockerSandbox):
        container_name = sandbox_obj.container_name
        _ACTIVE_SANDBOXES[container_name] = sandbox_obj
        tool_context.state["sandbox_id"] = container_name
        # Remove from state to prevent JSON serialization crash
        tool_context.state["sandbox"] = None
        return sandbox_obj

    return None

def cleanup_all_sandboxes():
    """Runs at process exit to stop and remove all active sandboxes."""
    if _ACTIVE_SANDBOXES:
        print(f"Process exiting. Cleaning up {len(_ACTIVE_SANDBOXES)} active sandbox containers...", flush=True)
        for sandbox_id, sandbox in list(_ACTIVE_SANDBOXES.items()):
            try:
                sandbox.stop()
            except Exception as e:
                print(f"Failed to clean up sandbox container '{sandbox_id}' on exit: {e}", flush=True)
        _ACTIVE_SANDBOXES.clear()

# Register the atexit handler
atexit.register(cleanup_all_sandboxes)


# Security boundaries: Allowed characters and file types
ALLOWED_PATH_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.\/]+$')
ALLOWED_FILE_PATTERN = re.compile(
    r'^([a-zA-Z0-9_\-\.\/]+)\.(py|toml|json|txt|md|yaml|yml|ini|cfg|pyi)$'
    r'|^[a-zA-Z0-9_\-\.]*(LICENSE|README|py\.typed|requirements[a-zA-Z0-9_\-\.]*)$',
    re.IGNORECASE
)

def validate_sandbox_path(filepath: str) -> str:
    """Validates that the filepath is a relative path strictly within the sandbox workspace.
    
    Prevents path traversal attacks and checks against allowed filename patterns.
    """
    if not isinstance(filepath, str):
        raise TypeError("Filepath must be a string.")
        
    # Check for path traversal attempts
    if re.search(r'(^|/|\\)\.\.(\/|\\|$)', filepath):
        raise ValueError(f"Security Policy Violation: Path traversal ('..') is not allowed: {filepath}")
        
    # Check for absolute paths
    if filepath.startswith("/") or filepath.startswith("\\") or re.match(r'^[a-zA-Z]:', filepath):
        raise ValueError(f"Security Policy Violation: Absolute paths are not allowed: {filepath}")
        
    # Normalize path separators
    normalized = filepath.replace("\\", "/")
    
    # Check character validation
    if not ALLOWED_PATH_PATTERN.match(normalized):
        raise ValueError(f"Security Policy Violation: Path contains invalid characters: {filepath}")
        
    # Check allowed file types/extensions
    filename = os.path.basename(normalized)
    if not ALLOWED_FILE_PATTERN.match(filename):
        raise ValueError(f"Security Policy Violation: File type/extension not allowed: {filename}")
        
    return normalized

def sanitize_command(command_args: list[str] | str) -> list[str]:
    """Sanitizes and validates the command to prevent shell chaining and command injection."""
    if isinstance(command_args, str):
        # Programmatically check string commands to block chaining
        for char in ["&&", ";", "|", "`", "$("]:
            if char in command_args:
                raise ValueError(f"Security Policy Violation: Command chaining/substitution characters ('{char}') are not allowed.")
        return shlex.split(command_args)
    
    if not isinstance(command_args, list):
        raise TypeError("Command must be a list of strings or a string.")
        
    # Check each argument in the list
    for arg in command_args:
        if not isinstance(arg, str):
            raise TypeError("All command arguments must be strings.")
        # Check if the argument contains chaining operators or command injection attempts
        for char in ["&&", ";", "|", "`", "$("]:
            if char in arg:
                raise ValueError(f"Security Policy Violation: Command chaining/substitution characters ('{char}') are not allowed.")
                
    return command_args

def validate_repo_url(repo_url: str):
    """Validates that the repo_url is a valid HTTPS GitHub repository URL."""
    pattern = r"^https://github\.com/[a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+(\.git)?$"
    if not re.match(pattern, repo_url.strip()):
        raise ValueError(f"Security Policy Violation: Invalid GitHub repository URL: {repo_url}")


def fetch_github_issue(issue_url: str, tool_context: ToolContext) -> dict:
    """Fetches details of a public GitHub issue.

    Args:
        issue_url: The full URL of the GitHub issue (e.g., 'https://github.com/owner/repo/issues/123').

    Returns:
        A dictionary containing the issue details or error status.
    """
    pattern = r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)"
    match = re.match(pattern, issue_url.strip())
    if not match:
        return {"status": "error", "message": "Invalid GitHub issue URL format."}
    
    owner, repo, issue_number = match.groups()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "BugRepro-Sentinel-Agent"
    }
    
    try:
        response = httpx.get(api_url, headers=headers, follow_redirects=True)
        if response.status_code != 200:
            return {"status": "error", "message": f"Failed to fetch issue. HTTP Status: {response.status_code}"}
        
        data = response.json()
        
        # Save issue details to session state for subsequent agents
        tool_context.state["issue_url"] = issue_url
        tool_context.state["issue_title"] = data.get("title", "")
        tool_context.state["issue_body"] = data.get("body", "")
        tool_context.state["repo_url"] = f"https://github.com/{owner}/{repo}.git"
        
        return {
            "status": "success",
            "owner": owner,
            "repo": repo,
            "issue_number": int(issue_number),
            "title": data.get("title", ""),
            "body": data.get("body", ""),
            "repo_url": f"https://github.com/{owner}/{repo}.git"
        }
    except Exception as e:
        return {"status": "error", "message": f"Exception occurred: {str(e)}"}


def clone_and_setup_repo(repo_url: str, tool_context: ToolContext) -> dict:
    """Clones a GitHub repository and sets up the environment in the Docker sandbox.

    Args:
        repo_url: The git URL of the repository (e.g. 'https://github.com/owner/repo.git').

    Returns:
        A dictionary containing the setup results, detected package files, and status.
    """
    try:
        validate_repo_url(repo_url)
    except Exception as e:
        return {"status": "error", "message": f"Repository URL validation failed: {str(e)}"}

    sandbox = get_sandbox(tool_context)
    if not sandbox:
        sandbox = DockerSandbox(image="python:3.11-slim")
        try:
            sandbox.start()
            _ACTIVE_SANDBOXES[sandbox.container_name] = sandbox
            tool_context.state["sandbox_id"] = sandbox.container_name
            tool_context.state["sandbox"] = None
        except Exception as e:
            return {"status": "error", "message": f"Failed to start sandbox: {str(e)}"}
    
    # Clone the repo. We update apt and install git first because python-slim does not have git by default.
    sandbox.execute(["apt-get", "update"], workdir="/")
    sandbox.execute(["apt-get", "install", "-y", "git"], workdir="/")
    
    # Clean workspace directory if git clone is called again
    sandbox.execute(["rm", "-rf", "/workspace"])
    sandbox.execute(["mkdir", "-p", "/workspace"], workdir="/")
    
    clone_res = sandbox.execute(["git", "clone", repo_url, "/workspace"], workdir="/")
    if clone_res["exit_code"] != 0:
        return {
            "status": "error",
            "message": f"Failed to clone repository: {clone_res['stdout']}"
        }
            
    # Detect configuration files
    ls_res = sandbox.execute(["ls", "-la"])
    files = ls_res["stdout"]
    
    setup_status = "unknown"
    install_log = ""
    
    # Install dependencies
    if "requirements.txt" in files:
        setup_status = "requirements.txt"
        install_res = sandbox.execute(["pip", "install", "-r", "requirements.txt"])
        install_log = install_res["stdout"]
    elif "pyproject.toml" in files:
        setup_status = "pyproject.toml"
        install_res = sandbox.execute(["pip", "install", "."])
        install_log = install_res["stdout"]
        # Also ensure pytest is installed
        sandbox.execute(["pip", "install", "pytest"])
    else:
        sandbox.execute(["pip", "install", "pytest"])
        setup_status = "no dependency file detected, installed pytest"
        
    return {
        "status": "success",
        "setup_method": setup_status,
        "install_log": install_log
    }


def run_sandbox_command(command_args: list[str], tool_context: ToolContext) -> dict:
    """Executes a command inside the active sandbox and returns the stdout and exit code.

    Args:
        command_args: The command and its arguments as a list of strings (e.g. ['pytest', 'tests/test_cli.py']).

    Returns:
        A dictionary containing 'exit_code', 'stdout', and 'status'.
    """
    try:
        sanitized_args = sanitize_command(command_args)
    except Exception as e:
        return {"status": "error", "message": f"Command validation failed: {str(e)}"}

    sandbox = get_sandbox(tool_context)
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    res = sandbox.execute(sanitized_args)
    return {
        "status": "success",
        "exit_code": res["exit_code"],
        "stdout": res["stdout"]
    }


def read_sandbox_file(filepath: str, tool_context: ToolContext) -> dict:
    """Reads the contents of a file in the active sandbox workspace.

    Args:
        filepath: The relative path to the file from the workspace root (e.g. 'src/cli.py').

    Returns:
        A dictionary containing the file content or an error message.
    """
    try:
        validated_path = validate_sandbox_path(filepath)
    except Exception as e:
        return {"status": "error", "message": f"Path validation failed: {str(e)}"}

    sandbox = get_sandbox(tool_context)
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    full_path = f"/workspace/{validated_path}"
    try:
        content = sandbox.read_file(full_path)
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read file '{filepath}': {str(e)}"}


def write_sandbox_file(filepath: str, content: str, tool_context: ToolContext) -> dict:
    """Writes content to a new or existing file in the active sandbox workspace.

    Args:
        filepath: The relative path to the file from the workspace root (e.g. 'tests/test_repro.py').
        content: The text content to write to the file.

    Returns:
        A dictionary containing the status of the file write.
    """
    try:
        validated_path = validate_sandbox_path(filepath)
    except Exception as e:
        return {"status": "error", "message": f"Path validation failed: {str(e)}"}

    sandbox = get_sandbox(tool_context)
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    full_path = f"/workspace/{validated_path}"
    try:
        sandbox.write_file(full_path, content)
        return {"status": "success", "message": f"Successfully wrote to '{filepath}'"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write file '{filepath}': {str(e)}"}


def patch_file_content(filepath: str, old_code: str, new_code: str, tool_context: ToolContext) -> dict:
    """Replaces a specific block of old code with new code in a file within the sandbox.

    Args:
        filepath: The relative path to the file from the workspace root (e.g. 'src/cli.py').
        old_code: The exact block of code to be replaced.
        new_code: The new code to insert in place of the old code.

    Returns:
        A dictionary containing the status of the patch.
    """
    try:
        validated_path = validate_sandbox_path(filepath)
    except Exception as e:
        return {"status": "error", "message": f"Path validation failed: {str(e)}"}

    sandbox = get_sandbox(tool_context)
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    full_path = f"/workspace/{validated_path}"
    try:
        current_content = sandbox.read_file(full_path)
    except Exception as e:
        return {"status": "error", "message": f"Failed to read file '{filepath}': {str(e)}"}
        
    if old_code not in current_content:
        return {
            "status": "error",
            "message": f"Could not find the target old_code block in '{filepath}'."
        }
        
    new_content = current_content.replace(old_code, new_code, 1)
    try:
        sandbox.write_file(full_path, new_content)
        return {"status": "success", "message": f"Successfully patched '{filepath}'"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write patched file '{filepath}': {str(e)}"}


def save_triage_decision(is_fixable: bool, reason: str, tool_context: ToolContext) -> dict:
    """Saves the triage decision to the session state.

    Args:
        is_fixable: True if the issue is reproducible and in-scope, False otherwise.
        reason: Explanation for the decision.

    Returns:
        A dictionary with the save status.
    """
    tool_context.state["triage_status"] = "FIXABLE" if is_fixable else "NOT_FIXABLE"
    tool_context.state["triage_reason"] = reason
    return {"status": "success", "triage_status": tool_context.state["triage_status"]}


def save_reproduction_results(reproduced: bool, failure_logs: str, test_file_path: str, tool_context: ToolContext) -> dict:
    """Saves the bug reproduction status and logs.

    Args:
        reproduced: True if the bug was successfully reproduced with a failing test.
        failure_logs: The command logs or test failures demonstrating the bug.
        test_file_path: The path of the reproduction test file.

    Returns:
        A dictionary with the save status.
    """
    tool_context.state["reproduction_status"] = "REPRODUCED" if reproduced else "NOT_REPRODUCED"
    tool_context.state["reproduction_logs"] = failure_logs
    tool_context.state["reproduction_test_file"] = test_file_path
    return {"status": "success"}


def save_patch_results(patched: bool, patch_details: str, tool_context: ToolContext) -> dict:
    """Saves the patch application status.

    Args:
        patched: True if the code patch was successfully applied to the source files.
        patch_details: Description of the changes made.

    Returns:
        A dictionary with the save status.
    """
    tool_context.state["patch_status"] = "PATCHED" if patched else "FAILED"
    tool_context.state["patch_details"] = patch_details
    return {"status": "success"}


def save_verification_results(passed: bool, logs: str, tool_context: ToolContext) -> dict:
    """Saves the verification results (whether tests passed) to the session state.

    If verification fails, records the details and logs of the failed patch 
    into 'patch_history' in state so the Patch Agent can analyze them.

    Args:
        passed: True if the tests passed after applying the patch.
        logs: Command line or test execution logs showing test outcomes.

    Returns:
        A dictionary with the save status.
    """
    tool_context.state["verification_status"] = "PASSED" if passed else "FAILED"
    tool_context.state["verification_logs"] = logs
    
    if not passed:
        # Save previous failed attempts in history for patch_agent context
        patch_history = tool_context.state.get("patch_history")
        if patch_history is None:
            patch_history = []
        
        patch_history.append({
            "patch_details": tool_context.state.get("patch_details", "No details"),
            "verification_logs": logs
        })
        tool_context.state["patch_history"] = patch_history
        
    return {"status": "success"}
