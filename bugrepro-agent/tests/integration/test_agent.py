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

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import app


def test_agent_stream() -> None:
    """
    Integration test for the agent stream functionality.
    Tests that the agent returns valid streaming responses.
    """

    session_service = InMemorySessionService()

    session = session_service.create_session_sync(user_id="test_user", app_name=app.name)
    runner = Runner(app=app, session_service=session_service)

    from unittest.mock import patch, MagicMock
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "title": "[BUG]: before_tool callback's lowercase_value() silently does nothing",
        "body": "The lowercase_value() function in customer_service/shared_libraries/callbacks.py (lines 96-106) contains two independent defects. Additionally, its only call site in before_tool() (line 113) discards the return value, making the intended lowercasing behavior ineffective.",
    }

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="Please triage and fix this issue: https://github.com/google/adk-samples/issues/2081")]
    )

    try:
        with patch("httpx.get", return_value=mock_response):
            events = list(
                runner.run(
                    new_message=message,
                    user_id="test_user",
                    session_id=session.id,
                    run_config=RunConfig(streaming_mode=StreamingMode.SSE),
                )
            )
        assert len(events) > 0, "Expected at least one message"
    finally:
        session_updated = session_service.get_session_sync(
            app_name=app.name,
            user_id="test_user",
            session_id=session.id
        )
        # 1. Clean up from the global registry
        from app.tools import _ACTIVE_SANDBOXES
        sandbox_id = session_updated.state.get("sandbox_id")
        if sandbox_id:
            sandbox = _ACTIVE_SANDBOXES.pop(sandbox_id, None)
            if sandbox:
                try:
                    sandbox.stop()
                except Exception:
                    pass
        # 2. Fallback to legacy sandbox key
        sandbox = session_updated.state.get("sandbox")
        if sandbox:
            try:
                sandbox.stop()
            except Exception:
                pass

    has_text_content = False
    for event in events:
        if (
            event.content
            and event.content.parts
            and any(part.text for part in event.content.parts)
        ):
            has_text_content = True
            break
    assert has_text_content, "Expected at least one message with text content"
