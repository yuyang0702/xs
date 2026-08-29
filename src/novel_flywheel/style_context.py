import re
import json
import hashlib
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from novel_flywheel.storage import atomic_write
from novel_flywheel.receipt_contracts import validate_final_review_verdict_receipt


DEFAULT_STYLE_RULES = (
    ("句子节奏", "长短交替，避免连续同构短句和整齐排比。"),
    ("描写密度", "只保留能推动动作、关系或判断的细节。"),
    ("情绪表达", "优先动作、选择和对话，不替读者总结感受。"),
    ("结尾方式", "停在人物的具体动作或关系变化，禁止抽象主题盖章。"),
    ("避免使用", "以下是润色版本、这一刻终于明白、不是命运而是选择。"),
)

PROSE_BASELINE_LABELS = {
    "summary": "整体风格",
    "viewpoint": "叙事视角",
    "narrative_distance": "叙事距离",
    "sentence_rhythm": "句子节奏",
    "paragraph_rhythm": "段落节奏",
    "dialogue": "对白方式",
    "psychology": "心理描写",
    "action_sensation": "动作与感官",
    "professional_detail": "专业细节",
    "forbidden_patterns": "避免使用",
}


def default_style_profile(metadata: dict) -> dict:
    return {
        "genre": metadata.get("genre") or "未指定",
        "viewpoint": metadata.get("pov") or metadata.get("perspective") or "跟随当前视角人物",
        "tone": metadata.get("tone") or "具体、克制、以场景推进",
        "rules": [{"label": label, "rule": rule} for label, rule in DEFAULT_STYLE_RULES],
    }


def ensure_style_profile(project: Any) -> str:
    path = Path(project.path) / "style-profile.md"
    baseline = Path(project.path) / "learning" / "prose_baseline.json"
    try:
        artifact = json.loads(baseline.read_text(encoding="utf-8"))
        baseline_data = artifact.get("data", {}) if artifact.get("status") == "active" else {}
        if not isinstance(baseline_data, dict):
            baseline_data = {}
    except (OSError, json.JSONDecodeError):
        baseline_data = {}
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if baseline_data.get("source") == "legacy_style_sample":
            text = re.sub(
                r"\n*<!-- STYLE_SAMPLE_START -->.*?<!-- STYLE_SAMPLE_END -->\n*", "\n",
                text, flags=re.S,
            ).rstrip() + "\n"
    else:
        profile_data = default_style_profile(project.metadata)
        text = (
            "# 作品专属文风档案\n\n"
            f"- 题材：{profile_data['genre']}\n"
            f"- 叙事视角：{profile_data['viewpoint']}\n"
            f"- 基础语调：{profile_data['tone']}\n"
            + "".join(f"- {item['label']}：{item['rule']}\n" for item in profile_data["rules"])
        )
        atomic_write(path, text)

    rules = []
    seen = set()
    for field, label in PROSE_BASELINE_LABELS.items():
        value = baseline_data.get(field)
        values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        for item in values:
            rule = item.strip() if isinstance(item, str) else ""
            if rule and rule not in seen and rule not in text:
                seen.add(rule)
                rules.append(f"- {label}：{rule}")
    if not rules:
        return text
    return text.rstrip() + "\n\n## 已确认基础文笔\n\n" + "\n".join(rules) + "\n"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def selected_style_reference_provenance(
    project: Any,
    quality_reference_group: dict | None = None,
    *,
    initialize_missing_profile: bool = False,
) -> dict[str, Any]:
    """Freeze the minimum trustworthy style/reference authority for one run.

    Confirmed quality references remain identity-only manual calibration.  Raw
    reference manuscripts never enter this contract or routine model prompts.
    """

    project_id = getattr(project, "id", None)
    if type(project_id) is not str or not project_id:
        raise ValueError("style/reference project identity is invalid")
    project_binding_sha256 = _canonical_sha256({
        "schema": "StyleReferenceProjectBindingV1",
        "version": 1,
        "project_id": project_id,
    })
    enabled = project.metadata.get("style_sample_scope") == "draft_and_polish"
    profile_path = Path(project.path) / "style-profile.md"
    profile_text = ""
    profile_bytes = b""
    profile_bytes_available = False
    profile_state = "not_requested"
    if enabled:
        if initialize_missing_profile and not profile_path.is_file():
            ensure_style_profile(project)
        try:
            profile_bytes = profile_path.read_bytes()
            profile_bytes_available = True
        except FileNotFoundError:
            profile_state = "missing"
        except OSError:
            profile_state = "unreadable"
        else:
            try:
                profile_text = profile_bytes.decode("utf-8")
                profile_state = "present"
            except UnicodeError:
                profile_state = "unreadable"
    profile_sha256 = (
        hashlib.sha256(profile_bytes).hexdigest()
        if profile_bytes_available else ""
    )
    baseline_path = Path(project.path) / "learning" / "prose_baseline.json"
    try:
        baseline_bytes = baseline_path.read_bytes()
        baseline_value = json.loads(baseline_bytes.decode("utf-8"))
        baseline_active = baseline_value.get("status") == "active"
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        baseline_bytes = b""
        baseline_active = False
    if quality_reference_group is None:
        group: dict[str, Any] = {}
    elif isinstance(quality_reference_group, dict):
        group = quality_reference_group
    else:
        raise ValueError("quality reference group must be an object")
    group_items = group.get("items", [])
    if not isinstance(group_items, list):
        raise ValueError("quality reference group items must be a list")
    group_id = group.get("id", "")
    group_version = group.get("version", 0)
    if group_items and (
        type(group_id) is not str
        or not group_id
        or type(group_version) is not int
        or group_version < 1
    ):
        raise ValueError("quality reference group identity is invalid")
    if not group_items and (
        group_id not in {"", None}
        or type(group_version) is not int
        or group_version != 0
    ):
        raise ValueError("empty quality reference group identity is invalid")
    group_project_id = group.get("project_id")
    if group_project_id is not None and (
        type(group_project_id) is not str or group_project_id != project_id
    ):
        raise ValueError("quality reference group project binding is invalid")
    reference_identities = []
    seen_reference_identities: set[tuple[str, ...]] = set()
    for item in group_items:
        if not isinstance(item, dict):
            raise ValueError("quality reference group item must be an object")
        fields = ("id", "role", "source_kind", "source_id", "version_id")
        if any(type(item.get(key)) is not str or not item[key] for key in fields):
            raise ValueError("quality reference identity field is invalid")
        identity = {key: item[key] for key in fields}
        identity_key = tuple(identity[key] for key in fields)
        if identity_key in seen_reference_identities:
            raise ValueError("quality reference identity is duplicated")
        seen_reference_identities.add(identity_key)
        reference_identities.append(identity)
    reference_identities.sort(key=lambda item: (
        item["id"], item["role"], item["source_kind"],
        item["source_id"], item["version_id"],
    ))
    selected = enabled or bool(reference_identities)
    identity_set_sha256 = _canonical_sha256(reference_identities)
    authority = {
        "schema": "SelectedStyleReferenceProvenanceV1",
        "version": 1,
        "project_binding_sha256": project_binding_sha256,
        "selection_status": "selected" if selected else "not_requested",
        "selection_scope": (
            "draft_and_polish"
            if enabled else
            "manual_score_calibration"
            if reference_identities else
            "not_requested"
        ),
        "style_profile_state": profile_state,
        "style_profile_sha256": profile_sha256,
        "prose_baseline_state": (
            "active" if baseline_active else
            "missing" if not baseline_path.exists() else
            "inactive_or_unreadable"
        ),
        "prose_baseline_sha256": (
            hashlib.sha256(baseline_bytes).hexdigest()
            if baseline_active else ""
        ),
        "quality_reference_group_id": group_id or "",
        "quality_reference_group_version": group_version,
        "quality_reference_group_state": (
            "present" if reference_identities else "not_requested"
        ),
        "quality_reference_identities": reference_identities,
        "quality_reference_identity_set_sha256": identity_set_sha256,
        "reference_evidence_status": (
            "identity_only_not_model_visible"
            if reference_identities else "none"
        ),
        "claim_policy": {
            "allowed": "uses_selected_style_guidance",
            "exact_imitation": "forbidden",
            "author_equivalence": "forbidden",
            "unsupported_stylistic_equivalence": "forbidden",
        },
    }
    authority_sha256 = _canonical_sha256(authority)
    return {
        **authority,
        "authority_sha256": authority_sha256,
        # This is kept in-memory/model-visible only.  Receipts must omit it.
        "style_profile_text": profile_text,
    }


def _public_style_reference_authority(
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(provenance, Mapping):
        raise ValueError("style/reference authority must be an object")
    public = {
        key: value for key, value in provenance.items()
        if key != "style_profile_text"
    }
    identity = public.pop("authority_sha256", None)
    expected_fields = {
        "schema", "version", "project_binding_sha256",
        "selection_status", "selection_scope",
        "style_profile_state", "style_profile_sha256",
        "prose_baseline_state", "prose_baseline_sha256",
        "quality_reference_group_id", "quality_reference_group_version",
        "quality_reference_group_state", "quality_reference_identities",
        "quality_reference_identity_set_sha256",
        "reference_evidence_status", "claim_policy",
    }
    if (
        set(public) != expected_fields
        or
        not isinstance(identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", identity) is None
        or _canonical_sha256(public) != identity
    ):
        raise ValueError("style/reference authority identity is invalid")
    if (
        public.get("schema") != "SelectedStyleReferenceProvenanceV1"
        or type(public.get("version")) is not int
        or public.get("version") != 1
        or not isinstance(public.get("project_binding_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}", public["project_binding_sha256"],
        ) is None
        or public.get("selection_status") not in {"selected", "not_requested"}
        or public.get("selection_scope") not in {
            "draft_and_polish", "manual_score_calibration", "not_requested",
        }
        or public.get("style_profile_state") not in {
            "present", "missing", "unreadable", "not_requested",
        }
        or not isinstance(public.get("style_profile_sha256"), str)
        or public.get("prose_baseline_state") not in {
            "active", "missing", "inactive_or_unreadable",
        }
        or not isinstance(public.get("prose_baseline_sha256"), str)
        or not isinstance(public.get("quality_reference_group_id"), str)
        or type(public.get("quality_reference_group_version")) is not int
        or public["quality_reference_group_version"] < 0
        or public.get("quality_reference_group_state") not in {
            "present", "not_requested",
        }
        or not isinstance(public.get("quality_reference_identities"), list)
        or not isinstance(
            public.get("quality_reference_identity_set_sha256"), str,
        )
        or public.get("reference_evidence_status") not in {
            "identity_only_not_model_visible", "none",
        }
        or type(public.get("claim_policy")) is not dict
        or public.get("claim_policy") != {
            "allowed": "uses_selected_style_guidance",
            "exact_imitation": "forbidden",
            "author_equivalence": "forbidden",
            "unsupported_stylistic_equivalence": "forbidden",
        }
    ):
        raise ValueError("style/reference authority semantic fields are invalid")
    identity_fields = {"id", "role", "source_kind", "source_id", "version_id"}
    if any(
        not isinstance(item, dict)
        or set(item) != identity_fields
        or any(type(item.get(key)) is not str or not item[key] for key in identity_fields)
        for item in public["quality_reference_identities"]
    ):
        raise ValueError("style/reference authority identity projection is invalid")
    identities = public["quality_reference_identities"]
    canonical_identities = sorted(identities, key=lambda item: (
        item["id"], item["role"], item["source_kind"],
        item["source_id"], item["version_id"],
    ))
    if (
        identities != canonical_identities
        or len({
            tuple(item[key] for key in (
                "id", "role", "source_kind", "source_id", "version_id",
            ))
            for item in identities
        }) != len(identities)
        or public["quality_reference_identity_set_sha256"]
        != _canonical_sha256(identities)
    ):
        raise ValueError("style/reference authority identity set is invalid")
    profile_state = public["style_profile_state"]
    profile_sha256 = public["style_profile_sha256"]
    if (
        (profile_state == "present" and
         re.fullmatch(r"[0-9a-f]{64}", profile_sha256) is None)
        or (profile_state in {"missing", "not_requested"} and
            profile_sha256 != "")
        or (profile_state == "unreadable" and profile_sha256 != "" and
            re.fullmatch(r"[0-9a-f]{64}", profile_sha256) is None)
    ):
        raise ValueError("style/reference profile state is inconsistent")
    baseline_state = public["prose_baseline_state"]
    baseline_sha256 = public["prose_baseline_sha256"]
    if (
        (baseline_state == "active" and
         re.fullmatch(r"[0-9a-f]{64}", baseline_sha256) is None)
        or (baseline_state != "active" and baseline_sha256 != "")
    ):
        raise ValueError("style/reference baseline state is inconsistent")
    has_references = bool(identities)
    if has_references:
        if (
            not public["quality_reference_group_id"]
            or public["quality_reference_group_version"] < 1
            or public["quality_reference_group_state"] != "present"
            or public["reference_evidence_status"]
            != "identity_only_not_model_visible"
        ):
            raise ValueError("style/reference group state is inconsistent")
    elif (
        public["quality_reference_group_id"] != ""
        or public["quality_reference_group_version"] != 0
        or public["quality_reference_group_state"] != "not_requested"
        or public["reference_evidence_status"] != "none"
    ):
        raise ValueError("style/reference absent group state is inconsistent")
    scope = public["selection_scope"]
    status = public["selection_status"]
    if scope == "draft_and_polish":
        valid_selection = status == "selected" and profile_state in {
            "present", "missing", "unreadable",
        }
    elif scope == "manual_score_calibration":
        valid_selection = (
            status == "selected"
            and profile_state == "not_requested"
            and profile_sha256 == ""
            and has_references
        )
    else:
        valid_selection = (
            status == "not_requested"
            and profile_state == "not_requested"
            and profile_sha256 == ""
            and not has_references
        )
    if not valid_selection:
        raise ValueError("style/reference selection state is inconsistent")
    return {**public, "authority_sha256": identity}


def validate_frozen_style_reference_authority(
    frozen: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare every frozen state, including explicit absence, without coercion."""

    frozen_public = _public_style_reference_authority(frozen)
    current_public = _public_style_reference_authority(current)
    if frozen_public != current_public:
        raise ValueError("selected style/reference authority changed during run")
    return frozen_public


def validate_style_reference_context_receipt(
    receipt: Mapping[str, Any],
    *,
    frozen_authority: Mapping[str, Any],
    stage: str,
    require_contract_attempt: bool = False,
    expected_model_input_sha256: str | None = None,
    expected_model_system_sha256: str | None = None,
    expected_context_packet_sha256: str | None = None,
    expected_contract_attempt_index: int | None = None,
    expected_contract_attempt_route: str | None = None,
) -> dict[str, Any]:
    """Validate the durable binding to the exact accepted model attempt."""

    public = _public_style_reference_authority(frozen_authority)
    required = {
        "schema", "version", "stage", "visibility",
        "selected_authority_sha256", "context_sha256",
        "style_profile_sha256",
        "context_packet_sha256", "model_system_sha256",
        "model_input_sha256", "advisory_shedding_occurred",
        "dispatch_binding_status", "receipt_sha256",
    }
    attempt_fields = {"contract_attempt_index", "contract_attempt_route"}
    expected = required | (attempt_fields if require_contract_attempt else set())
    if not isinstance(receipt, Mapping) or set(receipt) != expected:
        raise ValueError("style/reference context receipt shape is invalid")
    value = dict(receipt)
    identity = value.pop("receipt_sha256", None)
    if (
        not isinstance(identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", identity) is None
        or _canonical_sha256(value) != identity
    ):
        raise ValueError("style/reference context receipt identity is invalid")
    if (
        value.get("schema") != "StyleReferenceContextReceiptV1"
        or type(value.get("version")) is not int
        or value.get("version") != 1
        or value.get("stage") != stage
        or value.get("visibility") != "mandatory_current_contract"
        or value.get("selected_authority_sha256")
        != public["authority_sha256"]
        or value.get("style_profile_sha256")
        != public["style_profile_sha256"]
        or value.get("dispatch_binding_status") != "exact"
        or type(value.get("advisory_shedding_occurred")) is not bool
    ):
        raise ValueError("style/reference context receipt authority is invalid")
    # The raw profile is intentionally absent from the durable authority.  Its
    # exact digest, the Runtime-created rendered-context digest, and the exact
    # accepted system/input digests form the privacy-preserving verification
    # chain.  Re-render only when an in-memory caller deliberately supplies the
    # raw text; never require persisted raw profile bytes for validation.
    rendered = (
        render_selected_style_reference_context(
            dict(frozen_authority), stage=stage,
        )
        if "style_profile_text" in frozen_authority else ""
    )
    if (
        not isinstance(value.get("context_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["context_sha256"]) is None
        or rendered
        and value["context_sha256"]
        != hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    ):
        raise ValueError("style/reference rendered context binding is invalid")
    for field in (
        "context_packet_sha256", "model_system_sha256", "model_input_sha256",
    ):
        if (
            not isinstance(value.get(field), str)
            or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None
        ):
            raise ValueError(
                f"style/reference context receipt {field} is invalid"
            )
    if require_contract_attempt and (
        type(value.get("contract_attempt_index")) is not int
        or value["contract_attempt_index"] < 1
        or value.get("contract_attempt_route")
        not in {"primary", "configured_fallback"}
    ):
        raise ValueError("style/reference contract attempt binding is invalid")
    if (
        expected_model_input_sha256 is not None
        and value["model_input_sha256"] != expected_model_input_sha256
    ):
        raise ValueError("style/reference accepted model input binding is stale")
    if (
        expected_model_system_sha256 is not None
        and value["model_system_sha256"] != expected_model_system_sha256
    ):
        raise ValueError("style/reference accepted model system binding is stale")
    if (
        expected_context_packet_sha256 is not None
        and value["context_packet_sha256"]
        != expected_context_packet_sha256
    ):
        raise ValueError("style/reference accepted context packet binding is stale")
    if (
        expected_contract_attempt_index is not None
        and value.get("contract_attempt_index")
        != expected_contract_attempt_index
    ):
        raise ValueError("style/reference accepted attempt index is stale")
    if (
        expected_contract_attempt_route is not None
        and value.get("contract_attempt_route")
        != expected_contract_attempt_route
    ):
        raise ValueError("style/reference accepted attempt route is stale")
    return {**value, "receipt_sha256": identity}


def model_visible_style_reference_projection(
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only model-permitted authority; reference identities stay audit-only."""

    public = _public_style_reference_authority(provenance)
    return {
        "schema": "ModelVisibleStyleReferenceProjectionV1",
        "version": 1,
        "selection_status": public["selection_status"],
        "selection_scope": public["selection_scope"],
        "selected_authority_sha256": public["authority_sha256"],
        "style_profile_state": public["style_profile_state"],
        "style_profile_sha256": public["style_profile_sha256"],
        "prose_baseline_sha256": public["prose_baseline_sha256"],
        "quality_reference_identity_set_sha256": public[
            "quality_reference_identity_set_sha256"
        ],
        "reference_evidence_status": public["reference_evidence_status"],
        "claim_policy": public["claim_policy"],
    }


def render_selected_style_reference_context(
    provenance: dict[str, Any],
    *,
    stage: str,
) -> str:
    """Render stage-appropriate authority without overstating fidelity."""

    if provenance.get("selection_status") != "selected":
        return ""
    if stage not in {"planning", "draft", "polish", "final_review"}:
        return ""
    public = model_visible_style_reference_projection(provenance)
    raw_profile_text = provenance.get("style_profile_text", "")
    if type(raw_profile_text) is not str:
        raise ValueError("style/reference profile text is invalid")
    if public["style_profile_state"] == "present":
        if (
            hashlib.sha256(raw_profile_text.encode("utf-8")).hexdigest()
            != public["style_profile_sha256"]
        ):
            raise ValueError("style/reference profile text binding is stale")
    elif raw_profile_text != "":
        raise ValueError("style/reference unavailable profile has visible text")
    header = (
        "\n\nSELECTED STYLE/REFERENCE PROVENANCE (RUNTIME AUTHORITY):\n"
        + json.dumps(public, ensure_ascii=False, sort_keys=True)
    )
    if stage == "planning":
        return header + (
            "\nThe identity is trace-only at Planning. Do not imitate or infer "
            "reference prose and do not change formal event authority."
        )
    rendered = header + "\n\nPROJECT STYLE PROFILE:\n" + raw_profile_text
    if stage == "final_review":
        rendered += (
            "\n\nFIDELITY CLAIM POLICY:\n"
            "- Distinguish requested reference identity from model-visible, "
            "provenance-supported profile evidence.\n"
            "- Claim only uses_selected_style_guidance with exact manuscript evidence.\n"
            "- UNSUPPORTED_FIDELITY_CLAIMS_FORBIDDEN: never claim exact imitation, "
            "author equivalence, or unsupported stylistic equivalence.\n"
            "- Identity-only quality references are manual score calibration, not "
            "routine imitation targets."
        )
    return rendered


def _contains_unsupported_fidelity_claim(value: object) -> bool:
    def leaves(item: object) -> list[str]:
        if isinstance(item, str):
            return [item]
        if isinstance(item, Mapping):
            result: list[str] = []
            sibling_leaves: list[str] = []
            for key, child in item.items():
                key_leaves = leaves(key)
                child_leaves = leaves(child)
                result.extend(key_leaves)
                result.extend(child_leaves)
                result.extend(
                    f"{key_text}: {child_text}"
                    for key_text in key_leaves
                    for child_text in child_leaves
                )
                if isinstance(child, str):
                    sibling_leaves.extend(child_leaves)
            result.extend(
                f"{left}; {right}"
                for index, left in enumerate(sibling_leaves)
                for right in sibling_leaves[index + 1:]
            )
            return result
        if isinstance(item, (list, tuple)):
            return [text for child in item for text in leaves(child)]
        return []

    for raw_text in leaves(value):
        text = unicodedata.normalize("NFKC", raw_text).casefold()
        target = re.search(
            r"\b(author|writer|voice|style|reference|pen)\b|"
            r"作者|原作者|作家|文风|风格|声音|笔触|亲笔|参考",
            text,
        )
        equivalence = re.search(
            r"\b(indistinguishable|identical|equivalent|equivalence|"
            r"same\s+(?:as|pen)|could\s+have\s+come\s+from\s+the\s+same)\b|"
            r"无法区分|一模一样|等同|完全一致|同一人写|亲笔写成",
            text,
        )
        absolute = re.search(
            r"\b(exact|exactly|faithful|faithfully|perfect|perfectly|fully|"
            r"complete|completely)\b|精确|忠实|完美|完全|全部",
            text,
        )
        replication = re.search(
            r"\b(imitat\w*|replicat\w*|reproduc\w*|clon\w*|copy|copies|"
            r"copied|match\w*)\b|模仿|复制|复刻|再现|匹配",
            text,
        )
        authorship = re.search(
            r"\b(?:as\s+(?:if|though)|like)\b.{0,80}"
            r"\b(?:reference|selected|author|writer)\b.{0,40}"
            r"\b(?:wrote|written|authored)\b|"
            r"\b(?:reference|selected|same)\b.{0,80}"
            r"\b(?:author|writer)\b.{0,40}"
            r"\b(?:wrote|written|authored)\b|"
            r"(?:像是|仿佛|如同|参考|所选|原作者).{0,24}(?:作者|作家)?"
            r".{0,16}"
            r"(?:亲笔|写成|所写)",
            text,
        )
        if (absolute and replication) or (target and equivalence) or authorship:
            return True
    return False


def _contains_model_authored_reference_fidelity_assertion(value: object) -> bool:
    """Reserve reference-fidelity semantics for the Runtime typed claim.

    Model review fields remain free to report ordinary prose/style defects, but
    may not assert anything about equivalence or fidelity to a selected
    reference, author, writer, or novelist.  This is the structural boundary;
    phrase-level overclaim matching above is defense in depth only.
    """

    def leaves(item: object) -> list[str]:
        if isinstance(item, str):
            return [item]
        if isinstance(item, Mapping):
            result: list[str] = []
            sibling_leaves: list[str] = []
            for key, child in item.items():
                key_leaves = leaves(key)
                child_leaves = leaves(child)
                result.extend(key_leaves)
                result.extend(child_leaves)
                result.extend(
                    f"{key_text}: {child_text}"
                    for key_text in key_leaves
                    for child_text in child_leaves
                )
                if isinstance(child, str):
                    sibling_leaves.extend(child_leaves)
            result.extend(
                f"{left}; {right}"
                for index, left in enumerate(sibling_leaves)
                for right in sibling_leaves[index + 1:]
            )
            return result
        if isinstance(item, (list, tuple)):
            return [text for child in item for text in leaves(child)]
        return []

    for raw_text in leaves(value):
        text = unicodedata.normalize("NFKC", raw_text).casefold()
        reference_subject = re.search(
            r"\b(reference|exemplar|template|prototype|benchmark|"
            r"calibration)\b|"
            r"\bselected\s+(?:reference\s+)?(?:author|writer|style|voice)\b|"
            r"所选|选定|参考|原作者|亲笔",
            text,
        )
        fidelity_domain = re.search(
            r"\b(style|voice|manner|nuance|prose|writing|guidance|fidelity|"
            r"imitation|replication|equivalence|mirror\w*|lift\w*|borrow\w*|"
            r"deriv\w*|copy|copies|copied|clon\w*|reproduc\w*|wholesale|"
            r"verbatim|indistinguishable|identical|same|apart|tell)\b|"
            r"文风|风格|声音|笔触|神韵|细节|行文|写法|指导|保真|模仿|复刻|等同",
            text,
        )
        source_or_origin = re.search(
            r"\b(source|origin(?:al)?)\b|来源|原文|原作",
            text,
        )
        fidelity_relation = re.search(
            r"\b(fidelity|imitat\w*|replicat\w*|equivalence|mirror\w*|"
            r"lift\w*|borrow\w*|deriv\w*|copy|copies|copied|clon\w*|"
            r"reproduc\w*|verbatim|indistinguishable|identical|"
            r"same\s+(?:as|voice|style)|tell\s+apart)\b|"
            r"保真|模仿|复刻|等同|复制|照搬|借用|衍生|无法区分|一模一样",
            text,
        )
        if (
            reference_subject and fidelity_domain
        ) or (
            source_or_origin and fidelity_relation
        ):
            return True
    return False


def final_review_style_reference_receipt(
    provenance: dict[str, Any],
    review_payload: dict[str, Any],
    *,
    rendered_context_sha256: str = "",
    reviewed_input_sha256: str = "",
    claim: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bound Final Review claims to the frozen, model-visible evidence."""

    public = _public_style_reference_authority(provenance)
    # Fidelity is evaluated only over the closed, typed Final Review verdict
    # body.  Unknown free-text containers (for example an ad-hoc `summary`)
    # cannot become an alternate claim channel.
    typed_review_payload = validate_final_review_verdict_receipt(review_payload)
    if (
        _contains_model_authored_reference_fidelity_assertion(
            typed_review_payload
        )
        or _contains_unsupported_fidelity_claim(typed_review_payload)
    ):
        raise ValueError(
            "Final Review made an unsupported style/reference fidelity claim"
        )
    model_free_text_sha256 = _canonical_sha256(typed_review_payload)
    if public.get("selection_status") != "selected":
        receipt = {
            "schema": "FinalReviewStyleReferenceReceiptV1",
            "version": 1,
            "status": "not_requested",
            "selected_authority_sha256": public["authority_sha256"],
            "model_free_text_claim_authority": "none",
            "model_free_text_review_sha256": model_free_text_sha256,
            "claim": None,
        }
        receipt["receipt_sha256"] = _canonical_sha256(receipt)
        return receipt
    if (
        re.fullmatch(r"[0-9a-f]{64}", rendered_context_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", reviewed_input_sha256) is None
    ):
        raise ValueError("Final Review style/reference evidence binding is incomplete")
    profile_sha256 = public["style_profile_sha256"]
    profile_guidance_visible = public["style_profile_state"] == "present"
    reference_status = public["reference_evidence_status"]
    runtime_claim = (
        {
            "schema": "StyleReferenceFidelityClaimV1",
            "version": 1,
            "claim_category": "uses_selected_style_guidance",
            "claim_scope": "final_review_context",
            "evidence_sha256s": [
                public["authority_sha256"],
                profile_sha256,
                rendered_context_sha256,
                reviewed_input_sha256,
            ],
        }
        if profile_guidance_visible else None
    )
    if claim is not None and (
        not isinstance(claim, Mapping)
        or _canonical_sha256(dict(claim)) != _canonical_sha256(runtime_claim)
    ):
        raise ValueError("Final Review style/reference claim exceeds Runtime evidence")
    receipt = {
        "schema": "FinalReviewStyleReferenceReceiptV1",
        "version": 1,
        "status": (
            "selected_guidance_context_bound"
            if profile_guidance_visible else
            "calibration_identity_only_no_fidelity_claim"
            if reference_status == "identity_only_not_model_visible" else
            "selected_profile_unavailable_no_fidelity_claim"
        ),
        "selected_authority_sha256": public["authority_sha256"],
        "requested_style_profile_sha256": profile_sha256,
        "requested_reference_group_id": public[
            "quality_reference_group_id"
        ],
        "requested_reference_group_version": public[
            "quality_reference_group_version"
        ],
        "provenance_supported_evidence": (
            ["style_profile_sha256"] if profile_guidance_visible else []
        ),
        "reference_evidence_status": reference_status,
        "rendered_context_sha256": rendered_context_sha256,
        "reviewed_input_sha256": reviewed_input_sha256,
        "supported_claim_type": (
            "uses_selected_style_guidance"
            if profile_guidance_visible else "none"
        ),
        "claim": runtime_claim,
        "model_free_text_claim_authority": "none",
        "model_free_text_review_sha256": model_free_text_sha256,
        "fidelity_equivalence_proven": False,
        "unsupported_fidelity_claims": [],
    }
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    return receipt


def character_fingerprints(project_path: Path, segment: str, max_chars: int = 2400) -> str:
    folder = Path(project_path) / "characters"
    selected = []
    if not folder.is_dir():
        return ""
    for path in sorted(folder.glob("*.md")):
        if path.name == "_index.md":
            continue
        text = path.read_text(encoding="utf-8")
        heading = re.search(r"(?m)^#\s+(.+)$", text)
        name = heading.group(1).strip() if heading else path.stem
        if name not in segment:
            continue
        useful = [line.strip() for line in text.splitlines() if any(marker in line for marker in (
            "说话", "口头", "称呼", "语气", "句", "情绪", "禁用", "声音",
        ))]
        selected.append(f"## {name}\n" + "\n".join(useful[:8]))
    return "\n\n".join(selected)[:max_chars]
