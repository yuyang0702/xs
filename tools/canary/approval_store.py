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


class ApprovalConsumptionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def _path(self, cohort_id: str, suffix: str) -> Path:
        return self.root / f"{cohort_id}.{suffix}.json"

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
