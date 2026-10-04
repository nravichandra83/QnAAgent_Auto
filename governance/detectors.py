"""PII detectors for free text. Each returns spans; the masker resolves overlaps and tokenizes."""
import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from governance.policy import Policy
from governance.vault import Vault

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity_type: str
    source: str          # "regex" | "known" | "ner"


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_REGEXES: dict[str, re.Pattern] = {
    "SSN": re.compile(r"(?<![\w-])\d{3}[- ]\d{2}[- ]\d{4}(?![\w-])"),
    "CREDIT_CARD": re.compile(r"(?<![\w-])(?:\d[ -]?){12,15}\d(?![\w-])"),
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # NANP numbers with optional country/area code, and 7-digit local numbers like 555-0101;
    # not when glued to further digit groups (card or account numbers)
    "PHONE": re.compile(r"(?<![\w-])(?<!\d\s)(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])?"
                        r"\d{3}[\s.-]\d{4}(?![\w-])(?!\s\d)"),
}


class RegexDetector:
    def __init__(self, entities: tuple[str, ...]):
        unknown = set(entities) - set(_REGEXES)
        if unknown:
            raise ValueError(f"No regex for {sorted(unknown)}")
        self._entities = entities

    def detect(self, text: str, vault: Vault) -> list[Span]:
        spans = []
        for entity in self._entities:
            for m in _REGEXES[entity].finditer(text):
                if entity == "CREDIT_CARD" and not _luhn_ok(re.sub(r"\D", "", m.group())):
                    continue
                spans.append(Span(m.start(), m.end(), entity, "regex"))
        return spans


class KnownValueDetector:
    """Masks the values loaded into the session vault (the contract's customer profile),
    wherever they appear, case-insensitively and on word boundaries."""

    def __init__(self, min_length: int):
        self._min_length = min_length

    def detect(self, text: str, vault: Vault) -> list[Span]:
        spans = []
        for value, entity in vault.known_values():
            if len(value) < self._min_length:
                continue
            pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, value.split())) + r"(?!\w)"
            spans += [Span(m.start(), m.end(), entity, "known")
                      for m in re.finditer(pattern, text, re.IGNORECASE)]
        return spans


@lru_cache(maxsize=2)
def _presidio_analyzer(model: str):
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": model}]})
    return AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])


class NerDetector:
    """Names (and other configured entities) via Microsoft Presidio + spaCy.
    Loaded lazily; if Presidio is not installed the detector disables itself with a warning."""

    def __init__(self, model: str, entities: tuple[str, ...], min_score: float):
        self._model, self._entities, self._min_score = model, list(entities), min_score
        self.available = True

    def detect(self, text: str, vault: Vault) -> list[Span]:
        if not self.available:
            return []
        try:
            analyzer = _presidio_analyzer(self._model)
        except Exception as err:  # ImportError, missing spaCy model, ...
            log.warning("NER detector disabled: %s", err)
            self.available = False
            return []
        results = analyzer.analyze(text, language="en", entities=self._entities)
        return [Span(r.start, r.end, _NER_TYPES.get(r.entity_type, r.entity_type), "ner")
                for r in results if r.score >= self._min_score]


_NER_TYPES = {"LOCATION": "ADDRESS", "PHONE_NUMBER": "PHONE", "EMAIL_ADDRESS": "EMAIL", "US_SSN": "SSN"}


def build_text_detectors(policy: Policy, include_ner: bool = True) -> list:
    detectors: list = [RegexDetector(policy.regex_entities)]
    if policy.known_values_enabled:
        detectors.append(KnownValueDetector(policy.known_value_min_length))
    if include_ner and policy.ner_enabled:
        detectors.append(NerDetector(policy.ner_model, policy.ner_entities, policy.ner_min_score))
    return detectors
