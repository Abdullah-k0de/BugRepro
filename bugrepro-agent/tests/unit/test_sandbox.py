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
from app.sandbox import DockerSandbox


def test_docker_sandbox_lifecycle():
    # Use python:3.11-slim as a lightweight test container
    sandbox = DockerSandbox(image="python:3.11-slim")
    
    try:
        # 1. Start sandbox
        sandbox.start()
        assert sandbox.container is not None
        
        # 2. Write file
        test_path = "/workspace/test_hello.txt"
        test_content = "hello from sandbox test"
        sandbox.write_file(test_path, test_content)
        
        # 3. Read file
        read_content = sandbox.read_file(test_path)
        assert read_content == test_content
        
        # 4. Execute command
        res = sandbox.execute(["cat", test_path])
        assert res["exit_code"] == 0
        assert test_content in res["stdout"]
        
    finally:
        # 5. Stop sandbox
        sandbox.stop()
        assert sandbox.container is None
