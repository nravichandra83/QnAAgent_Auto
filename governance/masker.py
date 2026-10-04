"""Masking and unmasking.

- mask_text: free text (questions, DB error messages, outbound LLM payloads)
- mask_rows: query results, by column classification (from SQL lineage) plus a free-text
  scan of every remaining string cell
- unmask: tokens back to values for the end user, honouring reveal_to_user
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from governance.detectors import Span, build_text_detectors
from governance.policy import Policy
from governance.vault import TOKEN_RE, Vault

REDACTED = "[REDACTED]"


@dataclass
class MaskResult:
    text: str
    counts: Counter = field(default_factory=Counter)     # entity type -> values masked


class PiiMasker:
    def __init__(self, policy: Policy):
        self._policy = policy
        self._detectors = build_text_detectors(policy, include_ner=True)
        self._fast_detectors = build_text_detectors(policy, include_ner=False)

    def mask_text(self, text: str, vault: Vault, use_ner: bool = True) -> MaskResult:
        """use_ner=False for large machine-made text (prompts, error messages): regex and
        known values only, which is fast and has no false positives on SQL or schema text."""
        if not text:
            return MaskResult(text or "")
        detectors = self._detectors if use_ner else self._fast_detectors
        spans = [s for d in detectors for s in d.detect(text, vault)]
        chosen = self._resolve(text, spans)
        counts: Counter = Counter()
        for span in sorted(chosen, key=lambda s: s.start, reverse=True):
            token = vault.tokenize(text[span.start:span.end], span.entity_type)
            text = text[:span.start] + token + text[span.end:]
            counts[span.entity_type] += 1
        return MaskResult(text, counts)

    def _resolve(self, text: str, spans: list[Span]) -> list[Span]:
        """Drop allow-listed spans and spans inside existing tokens; on overlap keep the
        earliest, then the longest."""
        protected = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
        # Keep possessives outside the token: "Maria Lopez's" -> "<PERSON_1>'s", not "<PERSON_1>"
        spans = [Span(s.start, s.end - 2, s.entity_type, s.source)
                 if text[s.start:s.end].endswith(("'s", "’s")) else s for s in spans]
        candidates = [
            s for s in spans
            if not self._policy.is_allowed(text[s.start:s.end])
            and not any(a < s.end and s.start < b for a, b in protected)
        ]
        chosen: list[Span] = []
        for span in sorted(candidates, key=lambda s: (s.start, -(s.end - s.start))):
            if chosen and span.start < chosen[-1].end:
                continue
            chosen.append(span)
        return chosen

    def mask_rows(self, rows: list[dict[str, Any]], column_types: dict[str, str],
                  vault: Vault) -> tuple[list[dict[str, Any]], Counter]:
        counts: Counter = Counter()
        masked_rows = []
        for row in rows:
            masked = {}
            for column, value in row.items():
                entity = column_types.get(column)
                if value is not None and entity:
                    masked[column] = vault.tokenize(str(value), entity)
                    counts[entity] += 1
                elif isinstance(value, str):
                    result = self.mask_text(value, vault, use_ner=False)
                    masked[column] = result.text
                    counts.update(result.counts)
                else:
                    masked[column] = value      # numbers, dates, NULLs
            masked_rows.append(masked)
        return masked_rows, counts

    def unmask(self, text: str, vault: Vault) -> str:
        def restore(match):
            entity, value = match.group(1), vault.value_of(match.group(0))
            if value is None:
                return match.group(0)            # not ours: leave as written
            return value if self._policy.reveal.get(entity, False) else REDACTED
        return TOKEN_RE.sub(restore, text)
