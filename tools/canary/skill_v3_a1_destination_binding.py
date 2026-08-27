"""Non-secret, fail-closed destination contract for the Skill V3 A1 pilot.

The contract is derived only from the sealed route/model identity and the local
SQLite provider metadata.  It never loads credentials, constructs a Provider
client, or performs DNS/network I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from novel_flywheel.db import Database
from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tools.canary import skill_v3_character_heavy_pilot as pilot
from tools.canary import slice1_phase_b_current_skill as current_arm


DESTINATION_CONTRACT_VERSION = "skill-v3-a1-network-destination-binding-v1"
DESTINATION_ORIGIN_DOMAIN = "novel-flywheel-skill-v3-a1-destination-origin-v1"
EGRESS_POLICY_DOMAIN = "novel-flywheel-skill-v3-a1-egress-policy-v1"
DESTINATION_OPERATOR_THIRD_PARTY = "THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY"
DESTINATION_OPERATOR_OFFICIAL = "OFFICIAL_PROVIDER_ENDPOINT_LOCAL_METADATA_ONLY"


class SkillV3DestinationBindingError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(condition: bool, reason_code: str) -> None:
    if not condition:
        raise SkillV3DestinationBindingError(reason_code)


@dataclass(frozen=True)
class DestinationBindingV1:
    schema: str
    version: int
    contract_version: str
    scheme: str
    hostname: str
    port: int
    origin: str
    api_path: str
    provider_label: str
    model_label: str
    operator_class: str
    provider_descriptor_sha256: str
    model_binding_sha256: str
    route_fingerprint: str
    destination_origin_sha256: str
    allowed_destination_count: int
    cross_origin_redirect_allowed: bool
    unbound_proxy_route_allowed: bool
    unbound_base_url_override_allowed: bool

    def definition(self) -> dict[str, Any]:
        return asdict(self)


def _normalized_destination(base_url: str, protocol: str) -> tuple[str, str, int, str, str]:
    parts = urlsplit(base_url)
    _require(parts.scheme.casefold() == "https", "WRONG_SCHEME")
    _require(bool(parts.hostname), "MISSING_DESTINATION_BINDING")
    _require(parts.username is None and parts.password is None, "DESTINATION_CONTAINS_CREDENTIALS")
    _require(not parts.query and not parts.fragment, "DESTINATION_CONTAINS_UNBOUND_COMPONENT")
    hostname = str(parts.hostname).casefold()
    port = int(parts.port or 443)
    _require(port == 443, "WRONG_PORT")
    origin = f"https://{hostname}"
    base_path = parts.path.rstrip("/")
    _require(protocol == "anthropic", "WRONG_PROVIDER")
    api_path = f"{base_path}/messages" if base_path.endswith("/v1") else f"{base_path}/v1/messages"
    _require(api_path.startswith("/") and "//" not in api_path, "WRONG_PATH_PREFIX")
    return "https", hostname, port, origin, api_path


def resolve_a1_destination_binding_v1(
    *, repo_root: Path, route_database: Path,
) -> DestinationBindingV1:
    """Resolve the exact A1 destination without credential or network access."""

    repo = repo_root.resolve(strict=True)
    route_db = route_database.resolve(strict=True)
    route = current_arm.resolve_route_binding(route_db)
    _require(route.get("selected_route") == "primary", "WRONG_ROUTE")
    selected = route["routes"][0]
    _require(selected.get("route_fingerprint") == current_arm.EXPECTED_PRIMARY_ROUTE_FINGERPRINT, "WRONG_ROUTE")
    _require(selected.get("provider_descriptor_sha256") == current_arm.EXPECTED_PRIMARY_DESCRIPTOR, "WRONG_PROVIDER")
    _require(selected.get("model_binding_sha256") == current_arm.EXPECTED_PRIMARY_MODEL, "WRONG_MODEL")

    db = Database(route_db)
    role = db.get_role_binding("planning")
    _require(role is not None, "MISSING_DESTINATION_BINDING")
    provider = db.get_provider(str(role["primary_provider_id"]))
    model = db.get_model(str(role["primary_model_id"]))
    _require(provider is not None and model is not None, "MISSING_DESTINATION_BINDING")
    _require(bool(provider.get("enabled")), "WRONG_PROVIDER")
    scheme, hostname, port, origin, api_path = _normalized_destination(
        str(provider.get("base_url") or ""), str(provider.get("protocol") or ""),
    )
    model_input = pilot.reconstruct_sample_input(repo, "sv3s-089dd120ad568f87e7ef")
    _require(model_input.route_fingerprint == str(selected["route_fingerprint"]), "WRONG_ROUTE")
    _require(model_input.provider_descriptor_sha256 == str(selected["provider_descriptor_sha256"]), "WRONG_PROVIDER")
    _require(model_input.model_binding_sha256 == str(selected["model_binding_sha256"]), "WRONG_MODEL")
    provider_label = str(provider.get("name") or "UNKNOWN")
    model_label = str(model.get("model_name") or model.get("display_name") or "UNKNOWN")
    operator_class = (
        DESTINATION_OPERATOR_OFFICIAL
        if hostname == "api.anthropic.com" and str(provider.get("protocol")) == "anthropic"
        else DESTINATION_OPERATOR_THIRD_PARTY
    )
    origin_sha256 = domain_sha256(DESTINATION_ORIGIN_DOMAIN, {"origin": origin})
    return DestinationBindingV1(
        schema="SkillV3A1NetworkDestinationBindingV1",
        version=1,
        contract_version=DESTINATION_CONTRACT_VERSION,
        scheme=scheme,
        hostname=hostname,
        port=port,
        origin=origin,
        api_path=api_path,
        provider_label=provider_label,
        model_label=model_label,
        operator_class=operator_class,
        provider_descriptor_sha256=model_input.provider_descriptor_sha256,
        model_binding_sha256=model_input.model_binding_sha256,
        route_fingerprint=model_input.route_fingerprint,
        destination_origin_sha256=origin_sha256,
        allowed_destination_count=1,
        cross_origin_redirect_allowed=False,
        unbound_proxy_route_allowed=False,
        unbound_base_url_override_allowed=False,
    )


def a1_egress_policy_v1(repo_root: Path) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    sealed = pilot.load_sealed_pilot(repo)
    lock = next(row for row in sealed["locks"] if row["sample_slot"] == "A1")
    model_input = pilot.reconstruct_sample_input(repo, str(lock["sample_id"]))
    components = [
        {"component": "SYSTEM_CONTEXT", "egress_included": True, "source_identity_or_sha": model_input.system_sha256, "sensitivity_class": "PROJECT_CONTENT"},
        {"component": "TASK_ENVELOPE", "egress_included": True, "source_identity_or_sha": lock["task_sha256"], "sensitivity_class": "OPERATIONAL_METADATA"},
        {"component": "AUTHORITY_CONTEXT", "egress_included": True, "source_identity_or_sha": lock["authority_sha256"], "sensitivity_class": "PROJECT_CONTENT"},
        {"component": "STORY_SLICE", "egress_included": True, "source_identity_or_sha": lock["story_slice_sha256"], "sensitivity_class": "PROJECT_CONTENT"},
        {"component": "NON_SKILL_PROJECT_GUIDANCE", "egress_included": True, "source_identity_or_sha": lock["project_guidance_sha256"], "sensitivity_class": "CREATIVE_GUIDANCE"},
        {"component": "A_ARM_SKILL_CONTEXT", "egress_included": True, "source_identity_or_sha": model_input.skill_context_sha256, "sensitivity_class": "CREATIVE_GUIDANCE"},
        {"component": "OUTPUT_CONTRACT", "egress_included": True, "source_identity_or_sha": lock["output_contract_sha256"], "sensitivity_class": "OPERATIONAL_METADATA"},
        {"component": "PROVIDER_REQUEST_METADATA", "egress_included": True, "source_identity_or_sha": domain_sha256("novel-flywheel-skill-v3-a1-provider-request-metadata-v1", {"provider": model_input.provider_descriptor_sha256, "model": model_input.model_binding_sha256, "route": model_input.route_fingerprint, "output_cap": model_input.output_cap}), "sensitivity_class": "OPERATIONAL_METADATA"},
    ]
    excluded = {
        "raw_ref_corpus_egress": False,
        "raw_distill_evidence_excerpt_egress": False,
        "learn_node_raw_evidence_egress": False,
        "unrelated_project_data_egress": False,
        "other_sample_data_egress": False,
        "historical_blind_result_egress": False,
        "credential_egress": False,
        "local_file_path_egress": False,
    }
    body = {
        "schema": "SkillV3A1EgressPolicyV1",
        "version": 1,
        "sample_id": model_input.sample_id,
        "wire_input_sha256": model_input.wire_input_sha256,
        "components": components,
        "excluded": excluded,
    }
    return {**body, "egress_policy_sha256": domain_sha256(EGRESS_POLICY_DOMAIN, body)}


def validate_destination_authority_v1(
    value: Mapping[str, Any], *, destination: DestinationBindingV1,
    egress_policy_sha256: str,
) -> None:
    checks = (
        (value.get("destination_origin") == destination.origin, "WRONG_HOST"),
        (value.get("destination_origin_sha256") == destination.destination_origin_sha256, "APPROVAL_DESTINATION_SHA_MISMATCH"),
        (value.get("destination_path_or_prefix") == destination.api_path, "WRONG_PATH_PREFIX"),
        (value.get("destination_operator_class") == destination.operator_class, "DESTINATION_OPERATOR_MISMATCH"),
        (value.get("egress_policy_sha256") == egress_policy_sha256, "EGRESS_POLICY_SHA_MISMATCH"),
        (value.get("cross_origin_redirect_allowed") is False, "CROSS_ORIGIN_REDIRECT"),
        (value.get("unbound_proxy_route_allowed") is False, "UNBOUND_PROXY_ROUTE"),
    )
    for passed, reason in checks:
        _require(bool(passed), reason)


def request_target_is_exact_v1(target_url: str, destination: DestinationBindingV1) -> bool:
    parts = urlsplit(target_url)
    try:
        port = int(parts.port or 443)
    except ValueError:
        return False
    hostname = str(parts.hostname or "").casefold()
    origin = (
        f"{parts.scheme.casefold()}://{hostname}"
        + (f":{port}" if port != 443 else "")
    )
    return bool(
        parts.scheme.casefold() == destination.scheme
        and hostname == destination.hostname
        and port == destination.port
        and origin == destination.origin
        and parts.path == destination.api_path
        and not parts.query
        and not parts.fragment
        and parts.username is None
        and parts.password is None
    )
