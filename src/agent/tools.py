"""Tool definitions for the LLM agent (OpenAI-compatible function schemas)."""

from typing import Any


def get_tools() -> list[dict[str, Any]]:
    """Return the list of tools available to the LLM agent."""
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": (
                    "Execute Python code in a sandboxed Docker container to analyze data. "
                    "The code has access to pandas, numpy, matplotlib, seaborn, openpyxl. "
                    "The dataset is available at /workspace/dataset.<ext>. "
                    "Save any plots to /output/ as PNG files. "
                    "Print results, tables, and findings to stdout."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": (
                                "Python source code to execute. Must be valid, self-contained Python. "
                                "Use try/except where appropriate. Print results with print()."
                            ),
                        },
                    },
                    "required": ["code"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finalize_report",
                "description": (
                    "Finish the analysis and provide the final report to the user. "
                    "Call this when all necessary code has been executed and insights gathered."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "report": {
                            "type": "string",
                            "description": (
                                "The final analysis report: key metrics, insights, conclusions. "
                                "Use Markdown formatting. Mention any generated plots by filename."
                            ),
                        },
                    },
                    "required": ["report"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    ]


TOOL_NAMES = {tool["function"]["name"] for tool in get_tools()}
