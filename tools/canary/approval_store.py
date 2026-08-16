"""Single-use approval reservation and consumption receipts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Any

from novel_flywheel.runtime_fingerprint_build import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    domain_sha256,
)
from .approval_profiles import CanaryApprovalProfileError, approval_profile_for_schema


class CanaryApprovalReplay(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


LEDGER_IDENTITY_FILE = ".approval-ledger-identity-v1.json"


def initialize_approval_ledger_v1(
    root: Path, *, ledger_identity: str,
) -> dict[str, Any]:
    """Create or verify an empty, exact operational ledger root."""

    requested = Path(os.path.abspath(root))
    requested.mkdir(parents=True, exist_ok=True)
    resolved = requested.resolve(strict=True)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(requested)):
        raise CanaryApprovalReplay("approval_ledger_path_not_exact")
    for component in (requested, *requested.parents):
        attributes = getattr(component.stat(), "st_file_attributes", 0)
        if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise CanaryApprovalReplay("approval_ledger_reparse_point_forbidden")
        if component.parent == component:
            break
    if not isinstance(ledger_identity, str) or len(ledger_identity) != 64:
        raise CanaryApprovalReplay("approval_ledger_identity_invalid")
    business_entries = [
        item for item in resolved.iterdir() if item.name != LEDGER_IDENTITY_FILE
    ]
    if business_entries:
        raise CanaryApprovalReplay("approval_ledger_not_empty")
    identity_document = ApprovalConsumptionStore._definition(
        "CanaryApprovalLedgerIdentityV1", {
            "ledger_identity": ledger_identity,
            "initial_entry_count": 0,
            "business_content_included": False,
        },
    )
    identity_path = resolved / LEDGER_IDENTITY_FILE
    if identity_path.exists():
        try:
            existing = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CanaryApprovalReplay("approval_ledger_identity_invalid") from exc
        if existing != identity_document:
            raise CanaryApprovalReplay("approval_ledger_identity_mismatch")
    else:
        ApprovalConsumptionStore._exclusive_write(
            identity_path, identity_document,
            "approval_ledger_identity_already_exists",
        )
    return {
        "schema": "CanaryApprovalLedgerOperationalReadinessV1",
        "status": "exact",
        "ledger_identity": ledger_identity,
        "identity_definition_sha256": identity_document["definition_sha256"],
        "initial_entry_count": 0,
        "cohort_status": "unused",
        "approval_status": "unreserved",
        "credential_lookup_count": 0,
        "provider_client_creation_count": 0,
        "network_call_count": 0,
        "model_call_count": 0,
        "paid_model_call_count": 0,
    }


class ApprovalConsumptionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def _path(self, cohort_id: str, suffix: str) -> Path:
        return self.root / f"{cohort_id}.{suffix}.json"

    def operational_readiness(self, *, ledger_identity: str) -> dict[str, Any]:
        identity_path = self.root / LEDGER_IDENTITY_FILE
        try:
            value = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CanaryApprovalReplay(
                "approval_ledger_operational_readiness_unknown"
            ) from exc
        payload = value.get("payload") or {}
        if payload.get("ledger_identity") != ledger_identity:
            raise CanaryApprovalReplay("approval_ledger_identity_mismatch")
        business_entries = [
            item for item in self.root.iterdir()
            if item.name != LEDGER_IDENTITY_FILE
        ]
        if business_entries:
            raise CanaryApprovalReplay("approval_ledger_not_empty")
        return {
            "status": "exact", "ledger_identity": ledger_identity,
            "initial_entry_count": 0,
            "identity_definition_sha256": value.get("definition_sha256"),
        }

    @staticmethod
    def _identity(approval: Mapping[str, Any], *, executable: bool) -> tuple[str, str]:
        schema = approval.get("schema")
        try:
            _profile, kind = approval_profile_for_schema(str(schema))
        except CanaryApprovalProfileError:
            # Legacy C0A documents remain supported and never cross the real boundary.
            return "approval_sha256", str(approval["approval_sha256"])
        if kind == "candidate":
            if executable:
                raise CanaryApprovalReplay("approval_candidate_not_executable")
            return "approval_candidate_sha256", str(approval["approval_candidate_sha256"])
        if kind in {"authorization_patch", "authorization_patch_template"}:
            raise CanaryApprovalReplay("authorization_patch_not_executable")
        if kind == "signed_approval":
            return "signed_approval_sha256", str(approval["signed_approval_sha256"])
        raise CanaryApprovalReplay("approval_profile_unknown")

    @staticmethod
    def _profile_id(approval: Mapping[str, Any]) -> str:
        try:
            profile, _kind = approval_profile_for_schema(str(approval.get("schema")))
        except CanaryApprovalProfileError:
            return "legacy_c0a"
        declared = approval.get("profile_id")
        if declared is not None and declared != profile.profile_id:
            raise CanaryApprovalReplay("approval_profile_unknown")
        return profile.profile_id

    @staticmethod
    def _definition(schema: str, payload: Mapping[str, Any]) -> dict:
        body = {
            "schema": schema,
            "version": 1,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload": dict(payload),
        }
        return {
            **body,
            "definition_sha256": domain_sha256(
                f"novel-flywheel-canary:{schema}", body,
            ),
        }

    @staticmethod
    def _exclusive_write(path: Path, value: Mapping[str, Any], replay_code: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise CanaryApprovalReplay(replay_code) from exc
        try:
            os.write(descriptor, canonical_json_bytes(value) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def reserve(self, approval: Mapping[str, Any]) -> dict:
        identity_field, identity = self._identity(approval, executable=True)
        cohort_id = str(approval["single_use_cohort_id"])
        reserved = self._path(cohort_id, "reserved")
        consumed = self._path(cohort_id, "consumed")
        if consumed.exists():
            raise CanaryApprovalReplay("approval_already_consumed")
        receipt = self._definition("CanaryApprovalReservationV1", {
            "cohort_id": cohort_id,
            "profile_id": self._profile_id(approval),
            identity_field: identity,
            "approved_plan_sha256": approval["approved_plan_sha256"],
        })
        self._exclusive_write(reserved, receipt, "approval_already_reserved")
        return receipt

    def status(self, approval: Mapping[str, Any]) -> dict[str, Any]:
        """Read-only replay state for validate-only closure."""
        self._identity(approval, executable=False)
        cohort_id = str(approval["single_use_cohort_id"])
        reserved = self._path(cohort_id, "reserved").is_file()
        consumed = self._path(cohort_id, "consumed").is_file()
        return {
            "status": (
                "consumed" if consumed else "reserved" if reserved else "unused"
            ),
            "reserved": reserved,
            "consumed": consumed,
        }

    def consume(self, approval: Mapping[str, Any], evidence_sha256: str) -> dict:
        identity_field, identity = self._identity(approval, executable=True)
        cohort_id = str(approval["single_use_cohort_id"])
        reserved = self._path(cohort_id, "reserved")
        target = self._path(cohort_id, "consumed")
        if not reserved.is_file():
            raise CanaryApprovalReplay("approval_not_reserved")
        if target.exists():
            raise CanaryApprovalReplay("approval_already_consumed")
        try:
            reservation = json.loads(reserved.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CanaryApprovalReplay("approval_reservation_invalid") from exc
        if reservation.get("payload", {}).get(identity_field) != identity:
            raise CanaryApprovalReplay("approval_reservation_identity_mismatch")
        if reservation.get("payload", {}).get("profile_id") != self._profile_id(approval):
            raise CanaryApprovalReplay("approval_reservation_profile_mismatch")
        receipt = self._definition("CanaryApprovalConsumptionV1", {
            "cohort_id": cohort_id,
            "profile_id": self._profile_id(approval),
            identity_field: identity,
            "consumed_evidence_sha256": evidence_sha256,
        })
        self._exclusive_write(target, receipt, "approval_already_consumed")
        return receipt
