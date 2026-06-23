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

import re
import httpx
from google.adk.tools import ToolContext
from app.sandbox import DockerSandbox

def fetch_github_issue(issue_url: str) -> dict:
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
    sandbox = tool_context.state.get("temp:sandbox")
    if not sandbox:
        sandbox = DockerSandbox(image="python:3.11-slim")
        try:
            sandbox.start()
            tool_context.state["temp:sandbox"] = sandbox
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
    sandbox = tool_context.state.get("temp:sandbox")
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    res = sandbox.execute(command_args)
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
    sandbox = tool_context.state.get("temp:sandbox")
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    full_path = f"/workspace/{filepath}"
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
    sandbox = tool_context.state.get("temp:sandbox")
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    full_path = f"/workspace/{filepath}"
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
    sandbox = tool_context.state.get("temp:sandbox")
    if not sandbox:
        return {"status": "error", "message": "No active sandbox. Call clone_and_setup_repo first."}
    
    full_path = f"/workspace/{filepath}"
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
