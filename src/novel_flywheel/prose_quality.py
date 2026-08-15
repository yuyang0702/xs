from dataclasses import dataclass
import hashlib
import json
import re
from statistics import mean
from typing import Any, Iterable
import unicodedata


SEGMENT_SEPARATOR = "<!-- NOVEL_FLYWHEEL_SEGMENT -->"
SENTENCE_TERMINATOR = re.compile(
    r"(?:……|\.\.\.|[。！？.!?]+)[”’\"'）)】》〉〕］}]*"
)
PRODUCTION_PATTERNS = (
    r"以下(?:是|为).{0,20}(?:润色|修改|改写)(?:后|的)?(?:版本|正文)",
    r"(?:本片段|这个片段).{0,30}(?:不含|已经|修改)",
    r"(?:修改说明|润色说明|审核结论|作为AI|作为 AI)",
    r"(?m)^\s*(?:[-*]\s*)?\*{0,2}(?:状态变化|新问题|写作方法|核心功能|段\s*\d+\s*完结点)\*{0,2}\s*[：:]",
    r"SHORT_CAUSAL_CHAIN_JSON_(?:START|END)",
)
MIXED_SCRIPT = re.compile(r"(?:[\u4e00-\u9fff][A-Za-z]{2,}|[A-Za-z]{2,}[\u4e00-\u9fff])")
AUTHORITY_LATIN_NORMALIZATION_VERSION = "nfkc-case-sensitive-exact-token-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LATIN_TOKEN = re.compile(
    r"[A-Za-zＡ-Ｚａ-ｚ][A-Za-z0-9Ａ-Ｚａ-ｚ０-９]*"
    r"(?:(?:[._/\-．＿／－])[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+)*"
    r"(?:[+＋]{1,2})?"
)
_NORMALIZED_LATIN_TOKEN = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:(?:[._/\-])[A-Za-z0-9]+)*(?:\+{1,2})?"
)
UNICODE_REPLACEMENT = re.compile("\ufffd")
INVALID_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FORMULA_PATTERNS = (
    ("timestamp_scene_fragment", r"[-\u2014]{2}\s*[\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]{1,4}[\u70b9\u65f6\u6642:\uff1a][^\u3002\uff01\uff1f\n]{0,12}[\u3002\uff01\uff1f]\s*[^\u201c\u201d\n]{4,45}[\u3002\uff01\uff1f]"),
    ("epiphany_formula", r"这一刻.{0,12}(?:终于)?明白"),
    ("binary_formula", r"不是.{0,28}而是"),
    ("vague_metaphor", r"仿佛在(?:诉说|提醒|宣告)"),
    ("emotion_explained", r"(?:他|她)(?:这才)?明白了?[,，：:]"),
)
WEAK_ADVERBS = re.compile(r"微微|缓缓|轻轻|猛地|悄然|不由得|下意识")
THEME_ENDING = re.compile(r"(?:这座城市|这个时代|命运|时代).{0,30}(?:仍|还|继续|向前|运转|洪流)")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class AuthorityTermSourceArtifactV1:
    artifact_kind: str
    artifact_sha256: str
    contract: str
    version: int
    authority_status: str

    def __post_init__(self) -> None:
        if not self.artifact_kind.strip() or not self.contract.strip():
            raise ValueError("authority term source identity must not be empty")
        _require_sha256(self.artifact_sha256, "artifact_sha256")
        if self.version < 1:
            raise ValueError("authority term source version must be positive")
        if not self.authority_status.strip():
            raise ValueError("authority_status must not be empty")


@dataclass(frozen=True)
class AuthorityTermProjectionFieldV1:
    """One explicitly selected structured authority field.

    ``value`` remains process-local. Diagnostic projections retain only its
    field-path hash and any exact normalized term hash.
    """

    source_artifact_sha256: str
    field_path: str
    value: str
    segment_binding_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.source_artifact_sha256, "source_artifact_sha256")
        _require_sha256(self.segment_binding_sha256, "segment_binding_sha256")
        if not self.field_path.strip():
            raise ValueError("authority term field path must not be empty")


@dataclass(frozen=True)
class AuthorityApprovedLatinTermV1:
    normalized_term: str
    term_sha256: str
    source_artifact_sha256: str
    source_field_path_sha256: str
    segment_binding_sha256: str


@dataclass(frozen=True)
class AuthorityApprovedLatinTermSetV1:
    schema: str
    version: int
    normalization_version: str
    draft_authority_revision: int
    draft_authority_sha256: str
    source_artifacts: tuple[AuthorityTermSourceArtifactV1, ...]
    approved_terms: tuple[AuthorityApprovedLatinTermV1, ...]

    @property
    def term_set_sha256(self) -> str:
        return _canonical_sha256({
            "schema": self.schema,
            "version": self.version,
            "normalization_version": self.normalization_version,
            "draft_authority_revision": self.draft_authority_revision,
            "draft_authority_sha256": self.draft_authority_sha256,
            "source_artifacts": [
                {
                    "artifact_kind": item.artifact_kind,
                    "artifact_sha256": item.artifact_sha256,
                    "contract": item.contract,
                    "version": item.version,
                    "authority_status": item.authority_status,
                }
                for item in sorted(
                    self.source_artifacts,
                    key=lambda item: (
                        item.artifact_sha256, item.artifact_kind,
                        item.contract, item.version, item.authority_status,
                    ),
                )
            ],
            "approved_terms": [
                {
                    "normalized_term": item.normalized_term,
                    "term_sha256": item.term_sha256,
                    "source_artifact_sha256": item.source_artifact_sha256,
                    "source_field_path_sha256": item.source_field_path_sha256,
                    "segment_binding_sha256": item.segment_binding_sha256,
                }
                for item in sorted(
                    self.approved_terms,
                    key=lambda item: (
                        item.normalized_term, item.source_artifact_sha256,
                        item.source_field_path_sha256,
                        item.segment_binding_sha256,
                    ),
                )
            ],
        })

    def diagnostic_payload(self) -> dict[str, Any]:
        """Return the V1 hash-only representation; never persist raw terms."""

        return {
            "schema": self.schema,
            "version": self.version,
            "normalization_version": self.normalization_version,
            "draft_authority_revision": self.draft_authority_revision,
            "draft_authority_sha256": self.draft_authority_sha256,
            "source_artifacts": [
                {
                    "artifact_kind": item.artifact_kind,
                    "artifact_sha256": item.artifact_sha256,
                    "contract": item.contract,
                    "version": item.version,
                    "authority_status": item.authority_status,
                }
                for item in self.source_artifacts
            ],
            "approved_terms": [
                {
                    "term_sha256": item.term_sha256,
                    "term_length": len(item.normalized_term),
                    "character_classes": ["latin", "digit_or_ascii_joiner_optional"],
                    "source_artifact_sha256": item.source_artifact_sha256,
                    "source_field_path_sha256": item.source_field_path_sha256,
                    "segment_binding_sha256": item.segment_binding_sha256,
                }
                for item in self.approved_terms
            ],
            "term_set_sha256": self.term_set_sha256,
        }


@dataclass(frozen=True)
class DraftProseAuthorityContextV1:
    term_set: AuthorityApprovedLatinTermSetV1
    current_draft_authority_revision: int
    current_draft_authority_sha256: str
    current_segment_binding_sha256: str
    current_source_artifact_sha256s: tuple[str, ...]


def _is_cjk(value: str) -> bool:
    return bool(value) and "\u4e00" <= value <= "\u9fff"


def _token_continuation(value: str) -> bool:
    if not value or _is_cjk(value):
        return False
    normalized = unicodedata.normalize("NFKC", value)
    if len(normalized) == 1 and (
        normalized.isascii() and (
            normalized.isalnum() or normalized in "._/+-"
        )
    ):
        return True
    return unicodedata.category(value) in {"Pd", "Pc"}


def _normalize_latin_token(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", value)
    if _NORMALIZED_LATIN_TOKEN.fullmatch(normalized) is None:
        return None
    return normalized


def _latin_tokens(value: str) -> Iterable[tuple[re.Match[str], str | None, bool]]:
    for match in _LATIN_TOKEN.finditer(value):
        left = value[match.start() - 1] if match.start() else ""
        right = value[match.end()] if match.end() < len(value) else ""
        ambiguous = _token_continuation(left) or _token_continuation(right)
        normalized = _normalize_latin_token(match.group(0))
        yield match, normalized, ambiguous or normalized is None


def build_authority_approved_latin_term_set(
    *,
    draft_authority_revision: int,
    draft_authority_sha256: str,
    segment_binding_sha256: str,
    source_artifacts: Iterable[AuthorityTermSourceArtifactV1],
    fields: Iterable[AuthorityTermProjectionFieldV1],
) -> AuthorityApprovedLatinTermSetV1:
    """Project exact Latin terms from an explicit finite field allow-list."""

    if draft_authority_revision < 0:
        raise ValueError("draft authority revision must not be negative")
    _require_sha256(draft_authority_sha256, "draft_authority_sha256")
    _require_sha256(segment_binding_sha256, "segment_binding_sha256")
    artifacts = tuple(sorted(set(source_artifacts), key=lambda item: (
        item.artifact_sha256, item.artifact_kind, item.contract,
        item.version, item.authority_status,
    )))
    by_hash: dict[str, AuthorityTermSourceArtifactV1] = {}
    for artifact in artifacts:
        existing = by_hash.get(artifact.artifact_sha256)
        if existing is not None and existing != artifact:
            raise ValueError("one authority artifact hash has conflicting metadata")
        by_hash[artifact.artifact_sha256] = artifact
    approved: set[AuthorityApprovedLatinTermV1] = set()
    for field in fields:
        if field.source_artifact_sha256 not in by_hash:
            raise ValueError("authority term field source has no artifact provenance")
        if field.segment_binding_sha256 != segment_binding_sha256:
            raise ValueError("authority term field belongs to another segment")
        path_sha256 = hashlib.sha256(field.field_path.encode("utf-8")).hexdigest()
        for _match, normalized, ambiguous in _latin_tokens(field.value):
            if (
                ambiguous
                or normalized is None
                or sum(character.isalpha() for character in normalized) < 2
            ):
                continue
            approved.add(AuthorityApprovedLatinTermV1(
                normalized_term=normalized,
                term_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                source_artifact_sha256=field.source_artifact_sha256,
                source_field_path_sha256=path_sha256,
                segment_binding_sha256=segment_binding_sha256,
            ))
    return AuthorityApprovedLatinTermSetV1(
        schema="AuthorityApprovedLatinTermSetV1",
        version=1,
        normalization_version=AUTHORITY_LATIN_NORMALIZATION_VERSION,
        draft_authority_revision=draft_authority_revision,
        draft_authority_sha256=draft_authority_sha256,
        source_artifacts=artifacts,
        approved_terms=tuple(sorted(approved, key=lambda item: (
            item.normalized_term, item.source_artifact_sha256,
            item.source_field_path_sha256, item.segment_binding_sha256,
        ))),
    )


def _mixed_script_decision(
    token: str,
    normalized: str | None,
    ambiguous: bool,
    context: DraftProseAuthorityContextV1,
    *,
    term_set_sha256: str,
    approved_by_term: dict[str, tuple[AuthorityApprovedLatinTermV1, ...]],
    source_metadata: dict[str, AuthorityTermSourceArtifactV1],
) -> dict[str, Any]:
    term_set = context.term_set
    token_sha256 = hashlib.sha256(
        (normalized if normalized is not None else token).encode("utf-8")
    ).hexdigest()
    base: dict[str, Any] = {
        "schema": "DraftProseMixedScriptDecisionV1",
        "version": 1,
        "token_sha256": token_sha256,
        "token_length": len(normalized if normalized is not None else token),
        "character_classes": ["latin", "cjk_adjacent"],
        "normalization_version": term_set.normalization_version,
        "draft_authority_revision": context.current_draft_authority_revision,
        "draft_authority_sha256": context.current_draft_authority_sha256,
        "segment_binding_sha256": context.current_segment_binding_sha256,
        "term_set_sha256": term_set_sha256,
    }
    if (
        ambiguous
        or normalized is None
        or term_set.normalization_version
        != AUTHORITY_LATIN_NORMALIZATION_VERSION
    ):
        return {**base, "decision": "reject_ambiguous_term"}
    term_sources = {item.artifact_sha256 for item in term_set.source_artifacts}
    current_sources = set(context.current_source_artifact_sha256s)
    if (
        term_set.schema != "AuthorityApprovedLatinTermSetV1"
        or term_set.version != 1
        or term_set.draft_authority_revision
        != context.current_draft_authority_revision
        or term_set.draft_authority_sha256
        != context.current_draft_authority_sha256
        or any(
            item.authority_status != "accepted_current"
            for item in term_set.source_artifacts
        )
        or term_sources != current_sources
    ):
        return {**base, "decision": "reject_stale_authority"}
    matches = [
        item for item in approved_by_term.get(normalized, ())
        if item.normalized_term == normalized
        and item.term_sha256 == token_sha256
        and item.segment_binding_sha256
        == context.current_segment_binding_sha256
        and item.source_artifact_sha256 in current_sources
        and _SHA256.fullmatch(item.source_field_path_sha256) is not None
    ]
    if not matches:
        return {**base, "decision": "reject_unapproved_mixed_script"}
    return {
        **base,
        "decision": "exempt_authority_approved_term",
        "source_artifacts": [
            {
                "artifact_kind": source_metadata[item.source_artifact_sha256].artifact_kind,
                "artifact_sha256": item.source_artifact_sha256,
                "source_field_path_sha256": item.source_field_path_sha256,
                "contract": source_metadata[item.source_artifact_sha256].contract,
                "version": source_metadata[item.source_artifact_sha256].version,
                "authority_status": source_metadata[item.source_artifact_sha256].authority_status,
            }
            for item in sorted(matches, key=lambda value: (
                value.source_artifact_sha256,
                value.source_field_path_sha256,
            ))
        ],
    }


def _segment_for(text: str, offset: int) -> int:
    return text[:offset].count(SEGMENT_SEPARATOR) + 1


def _finding(code: str, text: str, match: re.Match[str], blocking: bool = False,
             severity: str = "medium") -> dict[str, Any]:
    start = max(0, match.start() - 28)
    end = min(len(text), match.end() + 48)
    return {
        "code": code,
        "severity": "critical" if blocking else severity,
        "blocking": blocking,
        "segment": _segment_for(text, match.start()),
        "excerpt": text[start:end].replace("\n", " ").strip(),
        "count": 1,
    }


def analyze_prose(
    text: str,
    *,
    authority_context: DraftProseAuthorityContextV1 | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    mixed_script_decisions: list[dict[str, Any]] = []
    for pattern in PRODUCTION_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            findings.append(_finding("production_text", text, match, True))
    legacy_mixed_matches = list(MIXED_SCRIPT.finditer(text))
    if authority_context is None:
        for match in legacy_mixed_matches:
            findings.append(_finding("mixed_script_corruption", text, match, True))
    else:
        term_set = authority_context.term_set
        term_set_sha256 = term_set.term_set_sha256
        approved_by_term_lists: dict[
            str, list[AuthorityApprovedLatinTermV1]
        ] = {}
        for approved in term_set.approved_terms:
            approved_by_term_lists.setdefault(
                approved.normalized_term, [],
            ).append(approved)
        approved_by_term = {
            term: tuple(items)
            for term, items in approved_by_term_lists.items()
        }
        source_metadata = {
            item.artifact_sha256: item for item in term_set.source_artifacts
        }
        legacy_index = 0
        for match, normalized, ambiguous in _latin_tokens(text):
            while (
                legacy_index < len(legacy_mixed_matches)
                and legacy_mixed_matches[legacy_index].end() <= match.start()
            ):
                legacy_index += 1
            if (
                legacy_index >= len(legacy_mixed_matches)
                or legacy_mixed_matches[legacy_index].start() >= match.end()
            ):
                continue
            if (
                normalized is not None
                and sum(character.isalpha() for character in normalized) < 2
            ):
                continue
            decision = _mixed_script_decision(
                match.group(0), normalized, ambiguous, authority_context,
                term_set_sha256=term_set_sha256,
                approved_by_term=approved_by_term,
                source_metadata=source_metadata,
            )
            mixed_script_decisions.append(decision)
            if decision["decision"] != "exempt_authority_approved_term":
                findings.append(
                    _finding("mixed_script_corruption", text, match, True)
                )
    for match in UNICODE_REPLACEMENT.finditer(text):
        findings.append(_finding("unicode_replacement_character", text, match, True))
    for match in INVALID_CONTROL.finditer(text):
        findings.append(_finding("invalid_control_character", text, match, True))
    seen_paragraphs: dict[str, re.Match[str]] = {}
    for match in re.finditer(r"(?ms)(?:^|\n\s*\n)([^\n].{23,}?)(?=\n\s*\n|\Z)", text):
        normalized = re.sub(r"\s+", "", match.group(1))
        if normalized in seen_paragraphs:
            findings.append(_finding("duplicate_paragraph", text, match, True))
        else:
            seen_paragraphs[normalized] = match
    for code, pattern in FORMULA_PATTERNS:
        matches = list(re.finditer(pattern, text))
        if matches:
            item = _finding(code, text, matches[0])
            item["count"] = len(matches)
            findings.append(item)
    weak = list(WEAK_ADVERBS.finditer(text))
    if len(weak) >= max(4, len(text) // 2500):
        item = _finding("weak_adverb_density", text, weak[0], severity="low")
        item["count"] = len(weak)
        findings.append(item)
    ending_start = max(0, len(text) - 500)
    ending_match = THEME_ENDING.search(text, ending_start)
    if ending_match:
        findings.append(_finding("theme_summary_ending", text, ending_match, severity="high"))
    metrics = prose_metrics(text)
    if metrics["one_sentence_paragraph_run"] >= 3:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
        sample = next((item for item in paragraphs if _sentence_count(item) == 1), text[:80])
        match = re.search(re.escape(sample), text)
        if match:
            item = _finding("one_sentence_paragraph_run", text, match)
            item["count"] = int(metrics["one_sentence_paragraph_run"])
            item["action"] = (
                "Merge consecutive one-sentence paragraphs that describe one continuous action; "
                "keep paragraph breaks only for dialogue, emphasis, suspense, or scene changes."
            )
            findings.append(item)
    if metrics["short_sentence_run"] >= 4:
        fake = re.search(r"[^。！？\n]{1,14}[。！？]", text)
        if fake:
            findings.append(_finding("uniform_short_sentence_run", text, fake))
    if metrics["dialogue_turn_run"] >= 4:
        fake = re.search(r"(?m)^[“\"]", text)
        if fake:
            item = _finding("dialogue_ping_pong", text, fake)
            item["count"] = int(metrics["dialogue_turn_run"])
            item["action"] = (
                "Break up four or more consecutive dialogue-only paragraphs with meaningful "
                "action, observation, hesitation, or changed subtext."
            )
            findings.append(item)
    blocking_count = sum(item["count"] for item in findings if item["blocking"])
    targeted_count = sum(item["count"] for item in findings if not item["blocking"])
    penalty = blocking_count * 30 + min(45, targeted_count * 5)
    result = {
        "naturalness_score": max(0, 100 - penalty),
        "blocking_count": blocking_count,
        "targeted_count": targeted_count,
        "findings": findings,
        "metrics": metrics,
    }
    if authority_context is not None:
        result["mixed_script_decisions"] = mixed_script_decisions
    return result


def prose_metrics(text: str) -> dict[str, float]:
    clean = text.replace(SEGMENT_SEPARATOR, "")
    narrative = re.sub(r'[“\"][^”\"\n]*[”\"]', "", clean)
    narrative = re.sub(r"(?m)^\s*#.*$", "", narrative)
    sentences = split_prose_sentences(narrative)
    all_sentences = split_prose_sentences(
        re.sub(r"(?m)^\s*#.*$", "", clean)
    )
    lengths = [len(SENTENCE_TERMINATOR.sub("", item).strip()) for item in sentences]
    short_run = run = 0
    for length in lengths:
        run = run + 1 if length <= 14 else 0
        short_run = max(short_run, run)
    dialogue_chars = sum(len(item) for item in re.findall(r"[“\"][^”\"\n]+[”\"]", clean))
    paragraph_run = dialogue_run = run = 0
    dialogue_current = 0
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", clean) if item.strip()]
    one_sentence_paragraph_count = 0
    for paragraph in paragraphs:
        is_single = (bool(paragraph) and not paragraph.startswith(("#", "“", '"'))
                     and _sentence_count(paragraph) == 1)
        one_sentence_paragraph_count += int(is_single)
        run = run + 1 if is_single else 0
        paragraph_run = max(paragraph_run, run)
        dialogue_current = dialogue_current + 1 if paragraph.startswith(("“", '"')) else 0
        dialogue_run = max(dialogue_run, dialogue_current)
    return {
        "sentence_count": float(len(all_sentences)),
        "short_sentence_count": float(sum(length <= 14 for length in lengths)),
        "paragraph_count": float(len(paragraphs)),
        "one_sentence_paragraph_count": float(one_sentence_paragraph_count),
        "one_sentence_paragraph_ratio": round(
            one_sentence_paragraph_count / max(1, len(paragraphs)), 3,
        ),
        "mean_sentence_length": round(mean(lengths), 2) if lengths else 0,
        "short_sentence_ratio": round(
            sum(length <= 14 for length in lengths) / len(lengths), 3,
        ) if lengths else 0,
        "short_sentence_run": float(short_run),
        "one_sentence_paragraph_run": float(paragraph_run),
        "dialogue_turn_run": float(dialogue_run),
        "dialogue_ratio": round(dialogue_chars / max(1, len(clean)), 3),
        "weak_adverb_density": round(len(WEAK_ADVERBS.findall(clean)) * 1000 / max(1, len(clean)), 3),
    }


def _sentence_count(text: str) -> int:
    return len(split_prose_sentences(text))


def split_prose_sentences(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sentences: list[str] = []
    start = 0
    for match in SENTENCE_TERMINATOR.finditer(normalized):
        sentence = normalized[start:match.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def compare_voice_metrics(current: dict[str, float], history: list[dict[str, float]]) -> dict[str, Any]:
    if not history:
        return {"drifted": False, "blocking": False, "signals": []}
    history = history[-5:]
    signals = []
    thresholds = {
        "mean_sentence_length": 0.45,
        "short_sentence_ratio": 0.35,
        "dialogue_ratio": 0.35,
        "weak_adverb_density": 1.0,
    }
    for key, threshold in thresholds.items():
        baseline = mean(item.get(key, 0.0) for item in history)
        delta = abs(current.get(key, 0.0) - baseline)
        relative = delta / max(abs(baseline), 0.05)
        if relative > threshold:
            signals.append({"metric": key, "current": current.get(key), "baseline": round(baseline, 3)})
    return {"drifted": bool(signals), "blocking": False, "signals": signals}
