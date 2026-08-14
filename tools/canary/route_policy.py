"""Exact role/stage/route authorization derived from the approved Plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class CanaryRouteBlocked(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class RouteObservation:
    stage: str
    role: str
    ordinal: int
    route_kind: str
    provider_descriptor_hash: str
    model_binding_hash: str
    protocol: str
    contract_sha256: str | None
    output_budget: int
    retry_fallback_reason: str | None


class ApprovedRoutePolicy:
    def __init__(self, approved_routes: list[Mapping[str, Any]]) -> None:
        self._routes = {str(item["role"]): dict(item) for item in approved_routes}

    def verify(self, observation: RouteObservation) -> None:
        route = self._routes.get(observation.role)
        if route is None:
            raise CanaryRouteBlocked("role_not_approved")
        if observation.stage not in route["allowed_stages"]:
            raise CanaryRouteBlocked("stage_not_approved_for_role")
        if observation.ordinal < 1:
            raise CanaryRouteBlocked("route_ordinal_invalid")
        selected_kind = "fallback" if observation.route_kind == "fallback" else "primary"
        selected = route.get(selected_kind)
        if not isinstance(selected, Mapping):
            raise CanaryRouteBlocked(f"{selected_kind}_route_not_approved")
        if selected.get("provider_descriptor_hash") != observation.provider_descriptor_hash:
            raise CanaryRouteBlocked("provider_descriptor_mismatch")
        if selected.get("model_binding_hash") != observation.model_binding_hash:
            raise CanaryRouteBlocked("model_binding_mismatch")
        if selected.get("protocol") != observation.protocol:
            raise CanaryRouteBlocked("provider_protocol_mismatch")
