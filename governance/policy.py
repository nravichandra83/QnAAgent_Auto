"""Loads governance/policy.yaml into a typed, immutable Policy."""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "policy.yaml"


@dataclass(frozen=True)
class Policy:
    reveal: dict[str, bool]                        # entity type -> shown to the end user?
    columns: dict[tuple[str, str], str]            # (table, column) lower-case -> entity type
    restricted_columns: frozenset[tuple[str, str]]
    regex_entities: tuple[str, ...]
    known_values_enabled: bool
    known_value_min_length: int
    ner_enabled: bool
    ner_model: str
    ner_entities: tuple[str, ...]
    ner_min_score: float
    allow_terms: frozenset[str]                    # casefolded
    allow_patterns: tuple[re.Pattern, ...]
    guard_mode: str                                # "mask" | "block"
    audit_path: Path
    audit_include_payloads: bool

    @property
    def restricted_column_names(self) -> set[str]:
        return {column for _, column in self.restricted_columns}

    def is_allowed(self, text: str) -> bool:
        stripped = text.strip()
        return stripped.casefold() in self.allow_terms or any(p.fullmatch(stripped) for p in self.allow_patterns)


def _split(qualified: str) -> tuple[str, str]:
    table, column = qualified.split(".")
    return table.lower(), column.lower()


@lru_cache
def load_policy(path: Path = DEFAULT_POLICY_PATH) -> Policy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entity_types = raw["entity_types"]
    columns = {_split(k): v for k, v in raw["columns"].items()}
    unknown = set(columns.values()) - set(entity_types)
    if unknown:
        raise ValueError(f"policy.yaml: columns use undefined entity types {sorted(unknown)}")
    detectors = raw["detectors"]
    guard_mode = raw["egress_guard"]["mode"]
    if guard_mode not in {"mask", "block"}:
        raise ValueError("policy.yaml: egress_guard.mode must be 'mask' or 'block'")
    return Policy(
        reveal={name: bool(cfg["reveal_to_user"]) for name, cfg in entity_types.items()},
        columns=columns,
        restricted_columns=frozenset(_split(c) for c in raw.get("restricted_columns", [])),
        regex_entities=tuple(detectors["regex"]),
        known_values_enabled=bool(detectors["known_values"]["enabled"]),
        known_value_min_length=int(detectors["known_values"]["min_length"]),
        ner_enabled=bool(detectors["ner"]["enabled"]),
        ner_model=detectors["ner"]["model"],
        ner_entities=tuple(detectors["ner"]["entities"]),
        ner_min_score=float(detectors["ner"]["min_score"]),
        allow_terms=frozenset(t.casefold() for t in raw["allow_list"]["terms"]),
        allow_patterns=tuple(re.compile(p) for p in raw["allow_list"]["patterns"]),
        guard_mode=guard_mode,
        audit_path=PROJECT_ROOT / raw["audit"]["path"],
        audit_include_payloads=bool(raw["audit"]["include_payloads"]),
    )
