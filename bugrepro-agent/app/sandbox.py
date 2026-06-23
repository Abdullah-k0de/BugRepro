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

import io
import os
import tarfile
import uuid
import logging
import docker

# Setup logging
logger = logging.getLogger("bugrepro.sandbox")
# Simple console handler setup in case parent logger doesn't output info
if not logger.handlers:
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


class DockerSandbox:
    """Manages an isolated, persistent Docker container for running tests safely."""

    def __init__(self, image: str, workspace_dir: str = "/workspace"):
        self.image = image
        self.workspace_dir = workspace_dir
        self.client = docker.from_env()
        self.container = None
        self.container_name = f"bugrepro-sandbox-{uuid.uuid4().hex[:8]}"

    def __deepcopy__(self, memo):
        # Prevent deepcopy from copying the client or container handles,
        # which fails on Windows due to uncopyable named pipe PyHANDLE objects.
        return self

    def start(self):
        """Starts the sandbox container in the background."""
        logger.info(f"Starting Docker sandbox container '{self.container_name}' using image '{self.image}'...")
        try:
            self.container = self.client.containers.run(
                self.image,
                command="tail -f /dev/null",
                detach=True,
                name=self.container_name,
                network_mode="bridge",
            )
            # Ensure workspace directory exists inside the container
            logger.info("Ensuring /workspace directory exists inside container...")
            self.execute(["mkdir", "-p", self.workspace_dir], workdir="/")
        except Exception as e:
            logger.error(f"Failed to start sandbox container: {e}")
            raise RuntimeError(f"Failed to start sandbox container: {e}")

    def execute(self, cmd: list[str], workdir: str = None) -> dict:
        """Executes a command inside the container and returns exit code, stdout, and stderr."""
        if not self.container:
            raise RuntimeError("Sandbox not started")

        if workdir is None:
            workdir = self.workspace_dir

        cmd_str = " ".join(cmd)
        logger.info(f"[Sandbox Exec] Command: '{cmd_str}' in directory: '{workdir}'")

        try:
            # We execute as a list of arguments directly to avoid shell expansion issues
            exec_res = self.container.exec_run(
                cmd,
                workdir=workdir,
            )
            stdout_str = exec_res.output.decode("utf-8", errors="replace")
            logger.info(f"[Sandbox Exec] Exit Code: {exec_res.exit_code}")
            
            # Print a log snippet of stdout if there is any output
            if stdout_str.strip():
                preview = stdout_str[:600] + "..." if len(stdout_str) > 600 else stdout_str
                logger.info(f"[Sandbox Exec Output Preview]:\n{preview}")
                
            return {
                "exit_code": exec_res.exit_code,
                "stdout": stdout_str,
                "stderr": "",  # Docker combines stdout/stderr in exec_run by default
            }
        except Exception as e:
            logger.error(f"[Sandbox Exec Error]: {e}")
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    def write_file(self, container_path: str, content: str):
        """Writes content to a file inside the container without host mounting."""
        if not self.container:
            raise RuntimeError("Sandbox not started")

        logger.info(f"[Sandbox Write] File: '{container_path}' ({len(content)} characters)")
        
        tar_stream = io.BytesIO()
        filename = os.path.basename(container_path)
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=filename)
            content_bytes = content.encode("utf-8")
            tarinfo.size = len(content_bytes)
            tar.addfile(tarinfo, io.BytesIO(content_bytes))

        tar_stream.seek(0)
        parent_dir = os.path.dirname(container_path)
        if not parent_dir:
            parent_dir = self.workspace_dir
        self.container.put_archive(parent_dir, tar_stream.read())

    def read_file(self, container_path: str) -> str:
        """Reads the content of a file from inside the container."""
        if not self.container:
            raise RuntimeError("Sandbox not started")

        logger.info(f"[Sandbox Read] File: '{container_path}'")

        try:
            stream, stat = self.container.get_archive(container_path)
            tar_stream = io.BytesIO(b"".join(stream))
            with tarfile.open(fileobj=tar_stream) as tar:
                member = tar.getmembers()[0]
                f = tar.extractfile(member)
                if f is not None:
                    return f.read().decode("utf-8", errors="replace")
                raise FileNotFoundError(
                    f"File {container_path} not found in archive"
                )
        except Exception as e:
            logger.error(f"[Sandbox Read Error]: Failed to read file {container_path}: {e}")
            raise FileNotFoundError(
                f"Failed to read file {container_path} from container: {e}"
            )

    def stop(self):
        """Stops and removes the container."""
        if self.container:
            logger.info(f"Stopping and removing Docker sandbox container '{self.container_name}'...")
            try:
                self.container.stop()
                self.container.remove()
                logger.info(f"Sandbox container '{self.container_name}' successfully cleaned up.")
            except Exception as e:
                logger.warning(f"Error cleaning up sandbox container: {e}")
            finally:
                self.container = None
