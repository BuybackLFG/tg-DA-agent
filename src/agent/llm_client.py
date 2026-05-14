import json
import logging
import re
from typing import Any

import openai

from src.config import settings
from src.agent.tools import TOOL_NAMES

logger = logging.getLogger(__name__)


class LLMAuthError(Exception):
    """Raised when LLM API authentication fails (401 Unauthorized)."""
    pass


class LLMClient:
    """Async OpenAI-compatible LLM client with tool-calling support and fallback parsing."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self._client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        logger.info(
            "LLMClient initialized (model=%s, base_url=%s)",
            self.model,
            self.base_url,
        )

    def _handle_error(self, exc: Exception) -> None:
        """Transform low-level API errors into meaningful exceptions."""
        error_str = str(exc).lower()
        if "401" in str(exc) or "unauthorized" in error_str:
            raise LLMAuthError(
                "Ошибка авторизации в LLM API. Проверьте LLM_API_KEY в файле .env."
            ) from exc
        raise

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request without tools.

        Returns:
            The message dict from the LLM response.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            message = response.choices[0].message
            return {
                "role": message.role,
                "content": message.content or "",
            }
        except Exception as exc:
            logger.error("LLM chat request failed: %s", exc)
            self._handle_error(exc)
            raise  # unreachable, _handle_error always raises

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Send a chat completion request with tool support.

        Returns:
            A tuple of (message_dict, list_of_tool_calls).
            If the model did not emit native tool_calls, a fallback parser
            attempts to extract JSON actions from the message content.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            message = response.choices[0].message
            msg_dict: dict[str, Any] = {
                "role": message.role,
                "content": message.content or "",
            }

            # Native tool calls
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })
                logger.info("Native tool calls received: %d", len(tool_calls))
                return msg_dict, tool_calls

            # Fallback: parse JSON from content
            fallback_calls = self._parse_fallback_tool_calls(message.content or "")
            if fallback_calls:
                logger.info("Fallback tool calls parsed: %d", len(fallback_calls))
                return msg_dict, fallback_calls

            return msg_dict, []

        except Exception as exc:
            logger.error("LLM chat_with_tools request failed: %s", exc)
            self._handle_error(exc)
            raise  # unreachable, _handle_error always raises

    def _parse_fallback_tool_calls(self, content: str) -> list[dict[str, Any]]:
        """Attempt to extract tool calls from free-form text when native tool_calling fails.

        Looks for JSON blocks with `name` and `arguments` / `code` fields,
        or explicit ```json ...``` blocks.
        """
        calls: list[dict[str, Any]] = []

        # Try to find ```json ... ``` blocks
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if not json_blocks:
            # Also try single backtick json blocks
            json_blocks = re.findall(r"`\s*(\{.*?\})\s*`", content, re.DOTALL)

        for block in json_blocks:
            try:
                data = json.loads(block)
                # Normalize various formats
                if isinstance(data, dict):
                    # Format: {"name": "execute_python", "arguments": {"code": "..."}}
                    name = data.get("name") or data.get("tool")
                    if name and name in TOOL_NAMES:
                        arguments = data.get("arguments") or data.get("params") or {}
                        # Some models may put 'code' directly at top level
                        if name == "execute_python" and "code" in data and "code" not in arguments:
                            arguments = {"code": data["code"]}
                        if name == "finalize_report" and "report" in data and "report" not in arguments:
                            arguments = {"report": data["report"]}
                        calls.append({
                            "id": f"fallback_{len(calls)}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        })
                elif isinstance(data, list):
                    for item in data:
                        name = item.get("name") or item.get("tool")
                        if name and name in TOOL_NAMES:
                            arguments = item.get("arguments") or item.get("params") or {}
                            if name == "execute_python" and "code" in item and "code" not in arguments:
                                arguments = {"code": item["code"]}
                            if name == "finalize_report" and "report" in item and "report" not in arguments:
                                arguments = {"report": item["report"]}
                            calls.append({
                                "id": f"fallback_{len(calls)}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments, ensure_ascii=False),
                                },
                            })
            except json.JSONDecodeError:
                continue

        # Heuristic: look for inline "Action:" patterns (ReAct style)
        if not calls:
            action_matches = re.findall(
                r'Action:\s*(\w+)\s*\nAction Input:\s*(\{.*?\}|".*?"|\S+)',
                content,
                re.DOTALL,
            )
            for name, arg_str in action_matches:
                if name in TOOL_NAMES:
                    try:
                        # Try to parse JSON, else wrap as string
                        if arg_str.strip().startswith("{"):
                            arguments = json.loads(arg_str)
                        else:
                            arguments = {"code": arg_str.strip().strip('"')}
                        calls.append({
                            "id": f"fallback_{len(calls)}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        })
                    except Exception:
                        continue

        return calls

    def build_tool_result_message(
        self,
        tool_call_id: str,
        function_name: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Build an OpenAI-compatible tool result message."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": function_name,
            "content": json.dumps(result, ensure_ascii=False, default=str),
        }
