import logging
import re
from dataclasses import dataclass
from typing import Pattern

logger = logging.getLogger(__name__)

# Thresholds
INPUT_MAX_LENGTH = 8000
MAX_INJECTION_SCORE = 2

# Blacklist phrases (case-insensitive, partial match)
BLACKLIST_PHRASES = [
    # English
    "ignore previous instructions",
    "ignore all instructions",
    "ignore the above",
    "ignore all above",
    "disregard previous",
    "disregard all instructions",
    "system prompt",
    "system instruction",
    "you are now",
    "you are a",
    "you are an",
    "DAN mode",
    "do anything now",
    "jailbreak",
    "developer mode",
    "override instructions",
    "override your",
    "forget everything",
    "forget all",
    "new instructions",
    "new role",
    "pretend to be",
    "act as a",
    "act as an",
    "reveal your prompt",
    "reveal your instructions",
    "show your system",
    "show your prompt",
    "leak your prompt",
    "leak your instructions",
    "this is a test",
    "testing purposes",
    "hypothetical scenario",
    "for educational purposes",
    "roleplay",
    "role play",
    "simulation mode",
    "debug mode",
    "admin mode",
    "sudo",
    "root access",
    "execute command",
    "run shell",
    "run system",
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
    "import os",
    "import subprocess",
    "bypass",
    "ignore safety",
    "ignore restrictions",
    "ignore rules",
    "no restrictions",
    "no limits",
    "no filter",
    "unfiltered",
    "uncensored",
    # Russian
    "игнорируй предыдущие",
    "игнорируй инструкции",
    "игнорируй все",
    "отмени предыдущие",
    "отмени инструкции",
    "забудь всё",
    "забудь все",
    "новые инструкции",
    "новая роль",
    "новый промпт",
    "раскрой свой промпт",
    "раскрой свои инструкции",
    "покажи системный",
    "покажи промпт",
    "системный промпт",
    "системные инструкции",
    "режим разработчика",
    "тестовый режим",
    "отладочный режим",
    "без ограничений",
    "без фильтров",
    "обойди защиту",
    "обойди ограничения",
    "выполни команду",
    "запусти shell",
    "режим админа",
]

# Regex patterns for structural injection attempts
STRUCTURAL_PATTERNS: list[Pattern] = [
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\s*instruction\s*>", re.IGNORECASE),
    re.compile(r"<\s*prompt\s*>", re.IGNORECASE),
    re.compile(r"===\s*SYSTEM", re.IGNORECASE),
    re.compile(r"---\s*SYSTEM", re.IGNORECASE),
    re.compile(r"###\s*SYSTEM", re.IGNORECASE),
    re.compile(r"\[\s*SYSTEM\s*\]", re.IGNORECASE),
    re.compile(r"\{\s*system\s*\}", re.IGNORECASE),
    re.compile(r"role\s*:\s*system", re.IGNORECASE),
    re.compile(r"user\s*:\s*.*ignore", re.IGNORECASE | re.DOTALL),
]

# Delimiter-like patterns that try to break message structure
DELIMITER_PATTERNS: list[Pattern] = [
    re.compile(r"-{3,}|={3,}|#{3,}", re.MULTILINE),
    re.compile(r"`{3,}", re.MULTILINE),
    re.compile(r"<\|.*?\|>", re.IGNORECASE),  # Special tokens like <|endoftext|>
]


@dataclass(frozen=True)
class GuardResult:
    is_safe: bool
    reason: str | None = None
    score: int = 0


class Guardrails:
    """Multi-layer guardrail for prompt injection detection and prevention."""

    @classmethod
    def check_input(cls, text: str | None) -> GuardResult:
        """Check user-provided text (context, instructions) for injection attempts."""
        if not text:
            return GuardResult(is_safe=True)

        if len(text) > INPUT_MAX_LENGTH:
            return GuardResult(
                is_safe=False,
                reason=f"Input too long: {len(text)} chars (max {INPUT_MAX_LENGTH})",
                score=999,
            )

        score = 0
        reasons: list[str] = []
        lowered = text.lower()

        # Heuristic: blacklist phrases
        for phrase in BLACKLIST_PHRASES:
            if phrase in lowered:
                score += 1
                reasons.append(f"blacklist phrase: '{phrase}'")

        # Heuristic: structural patterns
        for pattern in STRUCTURAL_PATTERNS:
            if pattern.search(text):
                score += 2
                reasons.append(f"structural pattern: {pattern.pattern}")

        # Heuristic: excessive delimiters (may indicate delimiter injection)
        delimiter_count = sum(len(p.findall(text)) for p in DELIMITER_PATTERNS)
        if delimiter_count > 5:
            score += 1
            reasons.append(f"excessive delimiters: {delimiter_count}")

        # Heuristic: repetition of system-related words
        system_word_count = sum(
            1 for word in ["system", "prompt", "instruction", "role"]
            if word in lowered
        )
        if system_word_count >= 3:
            score += 1
            reasons.append(f"system word density: {system_word_count}")

        if score >= MAX_INJECTION_SCORE:
            return GuardResult(
                is_safe=False,
                reason=f"Potential prompt injection detected (score={score}): {'; '.join(reasons[:3])}",
                score=score,
            )

        return GuardResult(is_safe=True, score=score)

    @classmethod
    def check_dataset_text(cls, text: str) -> GuardResult:
        """Check text content inside dataset cells for embedded instructions."""
        # Same as input check but with lower threshold since dataset cells can be suspicious
        if not text or len(text) < 20:
            return GuardResult(is_safe=True)

        score = 0
        reasons: list[str] = []
        lowered = text.lower()

        for phrase in BLACKLIST_PHRASES:
            if phrase in lowered:
                score += 2  # Higher weight for injection inside data
                reasons.append(f"blacklist in data: '{phrase}'")

        for pattern in STRUCTURAL_PATTERNS:
            if pattern.search(text):
                score += 3
                reasons.append(f"structural in data: {pattern.pattern}")

        if score >= 3:
            return GuardResult(
                is_safe=False,
                reason=f"Dataset contains potential injection (score={score}): {'; '.join(reasons[:2])}",
                score=score,
            )

        return GuardResult(is_safe=True, score=score)

    @classmethod
    def check_output(cls, text: str | None) -> GuardResult:
        """Check LLM output for signs it was compromised (e.g., revealing system prompt)."""
        if not text:
            return GuardResult(is_safe=True)

        score = 0
        reasons: list[str] = []
        lowered = text.lower()

        # Check if output contains system prompt fragments
        system_phrases = [
            "you are a data analysis agent",
            "you have access to",
            "workflow:",
            "rules:",
            "critical:",
            "system prompt",
            "system instruction",
        ]
        for phrase in system_phrases:
            if phrase in lowered:
                score += 2
                reasons.append(f"system leak: '{phrase}'")

        # Check for injection confirmation
        if any(phrase in lowered for phrase in ["i will ignore", "i am now", "i have overridden"]):
            score += 3
            reasons.append("behavior override detected")

        # Check for suspicious instruction repetition
        if "ignore previous" in lowered or "disregard" in lowered:
            score += 2
            reasons.append("suspicious instruction in output")

        if score >= 3:
            return GuardResult(
                is_safe=False,
                reason=f"Output validation failed (score={score}): {'; '.join(reasons[:2])}",
                score=score,
            )

        return GuardResult(is_safe=True, score=score)

    @classmethod
    def sanitize_for_display(cls, text: str) -> str:
        """Sanitize text for safe display in Telegram (escape HTML if needed)."""
        # Basic HTML escape to prevent rendering issues
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
