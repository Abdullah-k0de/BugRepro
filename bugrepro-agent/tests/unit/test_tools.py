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

import pytest
from unittest.mock import patch, MagicMock
from google.adk.tools import ToolContext
from app.tools import (
    fetch_github_issue,
    clone_and_setup_repo,
    run_sandbox_command,
    read_sandbox_file,
    write_sandbox_file,
    patch_file_content,
)
from app.sandbox import DockerSandbox


def test_fetch_github_issue_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "title": "Bug in CLI parser",
        "body": "The parser crashes when --file option is omitted.",
    }
    
    with patch("httpx.get", return_value=mock_response):
        res = fetch_github_issue("https://github.com/google/adk-samples/issues/2081")
        assert res["status"] == "success"
        assert res["owner"] == "google"
        assert res["repo"] == "adk-samples"
        assert res["issue_number"] == 2081
        assert res["title"] == "Bug in CLI parser"
        assert res["body"] == "The parser crashes when --file option is omitted."


def test_fetch_github_issue_invalid_url():
    res = fetch_github_issue("https://invalid-url.com/issues/123")
    assert res["status"] == "error"
    assert "Invalid GitHub issue URL" in res["message"]


def test_sandbox_tools_integration():
    # Use python:3.11-slim as a lightweight test container
    sandbox = DockerSandbox(image="python:3.11-slim")
    sandbox.start()
    
    try:
        # Create a mock ToolContext
        tool_context = MagicMock(spec=ToolContext)
        tool_context.state = {"temp:sandbox": sandbox}
        
        # Test write file
        filepath = "test_file.py"
        content = "def hello():\n    print('hello')\n\nhello()\n"
        write_res = write_sandbox_file(filepath, content, tool_context)
        assert write_res["status"] == "success"
        
        # Test read file
        read_res = read_sandbox_file(filepath, tool_context)
        assert read_res["status"] == "success"
        assert read_res["content"] == content
        
        # Test patch file
        patch_res = patch_file_content(
            filepath=filepath,
            old_code="print('hello')",
            new_code="print('world')",
            tool_context=tool_context
        )
        assert patch_res["status"] == "success"
        
        # Test read patched file
        read_patched = read_sandbox_file(filepath, tool_context)
        assert "print('world')" in read_patched["content"]
        assert "print('hello')" not in read_patched["content"]
        
        # Test run command
        cmd_res = run_sandbox_command(["python", f"/workspace/{filepath}"], tool_context)
        assert cmd_res["status"] == "success"
        assert cmd_res["exit_code"] == 0
        assert "world" in cmd_res["stdout"]
        
    finally:
        sandbox.stop()
