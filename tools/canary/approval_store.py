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
        cohort_id = str(approval["single_use_cohort_id"])
        reserved = self._path(cohort_id, "reserved")
        consumed = self._path(cohort_id, "consumed")
        if consumed.exists():
            raise CanaryApprovalReplay("approval_already_consumed")
        receipt = self._definition("CanaryApprovalReservationV1", {
            "cohort_id": cohort_id,
            "approval_sha256": approval["approval_sha256"],
            "approved_plan_sha256": approval["approved_plan_sha256"],
        })
        self._exclusive_write(reserved, receipt, "approval_already_reserved")
        return receipt

    def status(self, approval: Mapping[str, Any]) -> dict[str, Any]:
        """Read-only replay state for validate-only closure."""
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
        cohort_id = str(approval["single_use_cohort_id"])
        reserved = self._path(cohort_id, "reserved")
        target = self._path(cohort_id, "consumed")
        if not reserved.is_file():
            raise CanaryApprovalReplay("approval_not_reserved")
        if target.exists():
            raise CanaryApprovalReplay("approval_already_consumed")
        receipt = self._definition("CanaryApprovalConsumptionV1", {
            "cohort_id": cohort_id,
            "approval_sha256": approval["approval_sha256"],
            "consumed_evidence_sha256": evidence_sha256,
        })
        self._exclusive_write(target, receipt, "approval_already_consumed")
        return receipt
