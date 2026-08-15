"""Test-only retained-budget counterfactual for R1-PA1.

This module deliberately lives under ``tests``.  It imports the production
budget policy but never mutates a ContractRuntime or invokes a provider.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_flywheel.context_policy import expanded_output_budget


CANONICALIZATION_VERSION = "r1-pa1-counterfactual-canonical-json-v1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _canonical_sha256(domain: str, value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + encoded).hexdigest()


class RetainedOutputBudgetCounterfactualV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: Literal["RetainedOutputBudgetCounterfactualV1"] = Field(
        default="RetainedOutputBudgetCounterfactualV1", alias="schema",
        serialization_alias="schema",
    )
    version: Literal[1] = 1
    canonicalization_version: Literal[
        "r1-pa1-counterfactual-canonical-json-v1"
    ] = CANONICALIZATION_VERSION
    source_evidence_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    attempt_count: int = Field(ge=1)
    actual_request_sequence: tuple[int, ...]
    retained_counterfactual_sequence: tuple[int, ...]
    target_before_cap_sequence: tuple[int | None, ...]
    effective_after_cap_sequence: tuple[int, ...]
    declared_output_ceiling: int | None = Field(default=None, ge=1)
    input_tokens: int = Field(ge=0)
    context_window: int | None = Field(default=None, ge=1)
    first_divergence_attempt: int | None = Field(default=None, ge=1)
    whole_fallback_reachability: Literal["unknown_counterfactual"]
    changed_variable: Literal[
        "retain_approved_expansion_across_outer_runtime_reconstruction"
    ]
    unchanged_invariant_names: tuple[str, ...]
    invariant_before_sha256: str = Field(pattern=SHA256_PATTERN)
    invariant_after_sha256: str = Field(pattern=SHA256_PATTERN)
    result_sha256: str = Field(pattern=SHA256_PATTERN)


def simulate_retained_budget_counterfactual(
    *,
    actual_request_sequence: list[int] | tuple[int, ...],
    source_evidence_canonical_sha256: str,
    declared_output_ceiling: int | None = None,
    input_tokens: int = 0,
    context_window: int | None = None,
    unchanged_invariants: dict[str, Any] | None = None,
) -> RetainedOutputBudgetCounterfactualV1:
    """Derive the one-variable counterfactual using the real budget policy."""
    actual = tuple(actual_request_sequence)
    if not actual:
        raise ValueError("actual_request_sequence must not be empty")

    retained = [actual[0]]
    targets_before_cap: list[int | None] = [None]
    for _ in actual[1:]:
        target_before_cap = expanded_output_budget(retained[-1])
        effective = expanded_output_budget(
            retained[-1],
            input_tokens=input_tokens,
            context_window=context_window,
            declared_output_ceiling=declared_output_ceiling,
        )
        targets_before_cap.append(target_before_cap)
        if effective is None:
            raise AssertionError("a concrete prior budget must expand concretely")
        retained.append(effective)

    first_divergence = next(
        (index for index, pair in enumerate(zip(actual, retained), start=1)
         if pair[0] != pair[1]),
        None,
    )
    invariant_values = unchanged_invariants or {}
    invariant_sha = _canonical_sha256(
        "r1-pa1-counterfactual-unchanged-invariants-v1",
        invariant_values,
    )
    payload = {
        "schema": "RetainedOutputBudgetCounterfactualV1",
        "version": 1,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_evidence_canonical_sha256": source_evidence_canonical_sha256,
        "attempt_count": len(actual),
        "actual_request_sequence": actual,
        "retained_counterfactual_sequence": tuple(retained),
        "target_before_cap_sequence": tuple(targets_before_cap),
        "effective_after_cap_sequence": tuple(retained),
        "declared_output_ceiling": declared_output_ceiling,
        "input_tokens": input_tokens,
        "context_window": context_window,
        "first_divergence_attempt": first_divergence,
        "whole_fallback_reachability": "unknown_counterfactual",
        "changed_variable": (
            "retain_approved_expansion_across_outer_runtime_reconstruction"
        ),
        "unchanged_invariant_names": tuple(sorted(invariant_values)),
        "invariant_before_sha256": invariant_sha,
        "invariant_after_sha256": invariant_sha,
    }
    payload["result_sha256"] = _canonical_sha256(
        "r1-pa1-retained-budget-counterfactual-v1", payload,
    )
    return RetainedOutputBudgetCounterfactualV1.model_validate(payload)
