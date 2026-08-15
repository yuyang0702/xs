"""Currency-separated, conservative C0B pricing and reservation policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING
import threading
from typing import Mapping

from .budget import CanaryBudgetExceeded


SUPPORTED_CURRENCIES = frozenset({"USD", "CNY"})


@dataclass(frozen=True)
class PriceRuleV1:
    provider: str
    model: str
    relay_group: str
    currency: str
    unit_tokens: int
    input_rate_per_unit: Decimal
    cached_input_rate_per_unit: Decimal
    output_rate_per_unit: Decimal
    reasoning_token_rule: str
    source_type: str
    evidence_sha256: str
    effective_evidence_date: str

    def __post_init__(self) -> None:
        if self.currency not in SUPPORTED_CURRENCIES or self.unit_tokens != 1_000_000:
            raise ValueError("price_rule_currency_or_unit_invalid")
        if any(value < 0 for value in (
            self.input_rate_per_unit, self.cached_input_rate_per_unit,
            self.output_rate_per_unit,
        )):
            raise ValueError("price_rule_negative")
        if self.reasoning_token_rule not in {
            "included_in_completion_cap", "separate_if_reported",
        }:
            raise ValueError("reasoning_token_rule_invalid")

    def cost_microunits(
        self, *, input_tokens: int, cached_input_tokens: int,
        output_tokens: int, reasoning_tokens: int = 0,
    ) -> int:
        values = (input_tokens, cached_input_tokens, output_tokens, reasoning_tokens)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("usage_tokens_invalid")
        cached = min(input_tokens, cached_input_tokens)
        uncached = input_tokens - cached
        billable_output = output_tokens
        if self.reasoning_token_rule == "separate_if_reported":
            billable_output += reasoning_tokens
        # One currency unit = 1,000,000 microunits and rates are per 1M
        # tokens, so ceil(tokens * rate) is the exact integer-microunit charge.
        value = (
            Decimal(uncached) * self.input_rate_per_unit
            + Decimal(cached) * self.cached_input_rate_per_unit
            + Decimal(billable_output) * self.output_rate_per_unit
        )
        return int(value.to_integral_value(rounding=ROUND_CEILING))

    def sanitized_definition(self) -> dict:
        value = asdict(self)
        for field in (
            "input_rate_per_unit", "cached_input_rate_per_unit",
            "output_rate_per_unit",
        ):
            value[field] = format(value[field], "f")
        return value


class PriceCatalogV1:
    def __init__(self, rules: list[PriceRuleV1]) -> None:
        self._rules: dict[tuple[str, str, str], PriceRuleV1] = {}
        for rule in rules:
            key = (rule.provider, rule.model, rule.relay_group)
            if key in self._rules:
                raise ValueError("duplicate_price_rule")
            self._rules[key] = rule

    def require(self, provider: str, model: str, relay_group: str) -> PriceRuleV1:
        try:
            return self._rules[(provider, model, relay_group)]
        except KeyError as exc:
            raise KeyError("price_rule_not_found") from exc

    def definitions(self) -> list[dict]:
        return [
            self._rules[key].sanitized_definition() for key in sorted(self._rules)
        ]


class CanaryMonetaryBudgetV1:
    """Independent USD/CNY hard ceilings; no implicit FX conversion or refund."""

    def __init__(
        self, *, maximum_usd_microunits: int,
        maximum_cny_microunits: int,
        approved_fx_snapshot: Mapping[str, object] | None = None,
    ) -> None:
        if min(maximum_usd_microunits, maximum_cny_microunits) < 0:
            raise ValueError("monetary_ceiling_invalid")
        self.maximum = {
            "USD": maximum_usd_microunits, "CNY": maximum_cny_microunits,
        }
        self.approved_fx_snapshot = dict(approved_fx_snapshot or {}) or None
        self._reserved = {"USD": 0, "CNY": 0}
        self._reservations: list[dict] = []
        self._reconciliations: dict[int, dict] = {}
        self._lock = threading.Lock()

    def _normalized(self, costs: Mapping[str, int]) -> dict[str, int]:
        normalized = {"USD": int(costs.get("USD", 0)), "CNY": int(costs.get("CNY", 0))}
        if any(value < 0 for value in normalized.values()):
            raise CanaryBudgetExceeded("monetary_reservation_invalid")
        return normalized

    def _check_locked(self, normalized: Mapping[str, int]) -> None:
        for currency, value in normalized.items():
            reserved = self._reserved[currency]
            ceiling = self.maximum[currency]
            if reserved + value > ceiling:
                raise CanaryBudgetExceeded(
                    f"{currency.casefold()}_cost_budget_exceeded",
                    dimension=currency, approved_ceiling=ceiling,
                    already_reserved=reserved, requested_reservation=value,
                    remaining_before_request=max(0, ceiling - reserved),
                )

    def preview(self, costs: Mapping[str, int]) -> None:
        normalized = self._normalized(costs)
        with self._lock:
            self._check_locked(normalized)

    def reserve(self, costs: Mapping[str, int]) -> int:
        normalized = self._normalized(costs)
        with self._lock:
            self._check_locked(normalized)
            ordinal = len(self._reservations) + 1
            for currency, value in normalized.items():
                self._reserved[currency] += value
            self._reservations.append({"ordinal": ordinal, "costs": normalized})
            return ordinal

    def reconcile(
        self, ordinal: int, *, actual_costs: Mapping[str, int] | None,
        billing_receipt_reliable: bool,
    ) -> None:
        with self._lock:
            if not 1 <= ordinal <= len(self._reservations):
                raise CanaryBudgetExceeded("monetary_reservation_not_found")
            if not billing_receipt_reliable or actual_costs is None:
                self._reconciliations[ordinal] = {
                    "status": "unknown_billing_reservation_retained",
                }
                return
            actual = {"USD": int(actual_costs.get("USD", 0)), "CNY": int(actual_costs.get("CNY", 0))}
            if any(value < 0 for value in actual.values()):
                raise CanaryBudgetExceeded("actual_cost_invalid")
            reserved = self._reservations[ordinal - 1]["costs"]
            # Never refund here. If a reliable receipt exceeds the pre-reserve,
            # retain the overage in the ledger and fail closed for subsequent calls.
            overage = {
                currency: max(0, actual[currency] - reserved[currency])
                for currency in SUPPORTED_CURRENCIES
            }
            for currency, value in overage.items():
                self._reserved[currency] += value
            self._reconciliations[ordinal] = {
                "status": "reconciled_no_refund", "actual_costs": actual,
                "overage": overage,
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "schema": "CanaryMonetaryBudgetV1",
                "maximum_cost_microunits": dict(sorted(self.maximum.items())),
                "reserved_cost_microunits": dict(sorted(self._reserved.items())),
                "approved_fx_snapshot": self.approved_fx_snapshot,
                "reservations": list(self._reservations),
                "reconciliations": {
                    str(key): value for key, value in sorted(self._reconciliations.items())
                },
            }
