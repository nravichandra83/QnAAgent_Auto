"""Egress guard: the last check on every payload before it leaves for the LLM.

Earlier layers (input masking, row masking) should already have removed all PII; the guard
re-scans the final messages with regex and known-value detectors. In "mask" mode it masks
what it finds and reports it; in "block" mode it refuses the call.
"""
from collections import Counter

from langchain_core.messages import BaseMessage

from governance.masker import PiiMasker
from governance.vault import Vault


class PiiLeakError(RuntimeError):
    """Raised in block mode. Carries entity types and counts only, never values."""


class EgressGuard:
    def __init__(self, masker: PiiMasker, mode: str):
        self._masker = masker
        self._mode = mode

    def check(self, messages: list[BaseMessage], vault: Vault) -> tuple[list[BaseMessage], Counter]:
        findings: Counter = Counter()
        cleaned = []
        for message in messages:
            content = message.content if isinstance(message.content, str) else str(message.content)
            result = self._masker.mask_text(content, vault, use_ner=False)
            if result.counts:
                findings.update(result.counts)
                message = message.model_copy(update={"content": result.text})
            cleaned.append(message)
        if findings and self._mode == "block":
            raise PiiLeakError(f"Blocked LLM call: payload contained PII {dict(findings)}")
        return cleaned, findings
