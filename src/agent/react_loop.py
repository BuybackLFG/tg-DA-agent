import json
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

from src.agent.llm_client import LLMClient
from src.agent.tools import get_tools
from src.agent.prompts import build_analysis_messages
from src.agent.executor import execute_python
from src.agent.guardrails import Guardrails

logger = logging.getLogger(__name__)

MAX_STEPS = 10


async def run_analysis(
    bot: Bot,
    chat_id: int,
    dataset_path: str,
    profile: dict,
    user_context: str,
    status_message: Message,
) -> tuple[str, dict[str, bytes]]:
    """Run the ReAct analysis loop.

    Returns:
        (final_report_text, output_files_dict)
    """
    llm = LLMClient()
    tools = get_tools()

    # Base messages (system + dataset context)
    base_messages = build_analysis_messages(profile, user_context)
    history: list[dict] = []
    collected_files: dict[str, bytes] = {}

    for step in range(1, MAX_STEPS + 1):
        await status_message.edit_text(f"🧠 Шаг {step}/{MAX_STEPS}: планирую анализ...")

        # Compose full messages: base + previous history
        current_messages = base_messages + history

        try:
            msg_dict, tool_calls = await llm.chat_with_tools(current_messages, tools)
        except Exception as exc:
            logger.error("LLM call failed at step %s: %s", step, exc)
            return f"Ошибка при обращении к LLM: {exc}", collected_files

        # No tool calls -> model gave a direct answer (treat as report)
        if not tool_calls:
            content = msg_dict.get("content", "Анализ завершён без результатов.")
            logger.info("No tool calls at step %s, finishing with direct answer.", step)

            output_guard = Guardrails.check_output(content)
            if not output_guard.is_safe:
                logger.warning("Output guardrail triggered on direct answer: %s", output_guard.reason)
                return (
                    f"⚠️ Ответ был заблокирован системой безопасности.\n"
                    f"Причина: {output_guard.reason}\n\n"
                    f"Попробуйте переформулировать запрос.",
                    collected_files,
                )

            return content, collected_files

        # Add assistant message (with tool_calls) to history
        assistant_msg = msg_dict.copy()
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": tc["type"],
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in tool_calls
        ]
        history.append(assistant_msg)

        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError as exc:
                logger.error("Failed to parse tool arguments: %s", exc)
                result = {"error": f"Invalid arguments JSON: {exc}"}
                history.append(llm.build_tool_result_message(tc["id"], name, result))
                continue

            if name == "execute_python":
                code = args.get("code", "")

                # Guardrails: check generated code for obvious malicious patterns
                code_guard = Guardrails.check_input(code)
                if not code_guard.is_safe:
                    logger.warning("Code guardrail triggered at step %s: %s", step, code_guard.reason)
                    result = {"error": f"Generated code was blocked by security policy: {code_guard.reason}"}
                    history.append(llm.build_tool_result_message(tc["id"], name, result))
                    continue

                await status_message.edit_text(f"🐍 Шаг {step}/{MAX_STEPS}: выполняю код...")
                logger.info("Step %s: executing Python sandbox", step)

                exec_result = await execute_python(
                    code=code,
                    dataset_path=dataset_path,
                )

                # Collect any generated plots/files
                for fname, fdata in exec_result.output_files.items():
                    collected_files[fname] = fdata

                # Build concise result for LLM (don't send raw bytes)
                result_payload = {
                    "stdout": exec_result.stdout[:4000] if exec_result.stdout else "",
                    "stderr": exec_result.stderr[:2000] if exec_result.stderr else "",
                    "returncode": exec_result.returncode,
                    "timed_out": exec_result.timed_out,
                    "output_files": list(exec_result.output_files.keys()),
                }
                history.append(
                    llm.build_tool_result_message(tc["id"], name, result_payload)
                )

                logger.info(
                    "Step %s: sandbox done (rc=%s, files=%s)",
                    step,
                    exec_result.returncode,
                    list(exec_result.output_files.keys()),
                )

            elif name == "finalize_report":
                report = args.get("report", "")
                logger.info("Step %s: finalizing report", step)

                # Guardrails: validate output report
                output_guard = Guardrails.check_output(report)
                if not output_guard.is_safe:
                    logger.warning("Output guardrail triggered: %s", output_guard.reason)
                    return (
                        f"⚠️ Сгенерированный отчёт был заблокирован системой безопасности.\n"
                        f"Причина: {output_guard.reason}\n\n"
                        f"Попробуйте переформулировать запрос или загрузить другой датасет.",
                        collected_files,
                    )

                return report, collected_files

            else:
                # Unknown tool
                result = {"error": f"Unknown tool: {name}"}
                history.append(
                    llm.build_tool_result_message(tc["id"], name, result)
                )

    # Max steps exceeded
    logger.warning("Max steps (%s) exceeded without finalize_report", MAX_STEPS)
    return (
        "Анализ был прерван: превышен лимит шагов. "
        "Попробуйте уточнить запрос или разбить задачу на части.",
        collected_files,
    )
