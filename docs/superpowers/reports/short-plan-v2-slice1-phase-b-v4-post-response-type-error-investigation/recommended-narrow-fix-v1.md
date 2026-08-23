# Recommended narrow fix — not implemented

`PRODUCTION_FIX_IMPLEMENTED=NO`

- `FIX_OWNER=tools.canary.slice1_phase_b_v4_single_dispatch.execute_authorized_once`
- `FIX_LINE=896`
- `FIX_KIND=PYDANTIC_JSON_MODE_AUDIT_SERIALIZATION`
- `INPUT_CONTRACT_BEFORE=dataclasses.asdict requires a dataclass instance`
- `INPUT_CONTRACT_AFTER=ArtifactConversionAudit.model_dump(mode="json") produces the canonical JSON-compatible mapping`
- `SEMANTIC_CHANGE=NO`
- `PROMPT_CHANGE=NO`
- `SKILL_CHANGE=NO`
- `ROUTE_MODEL_CHANGE=NO`
- `TRANSPORT_GUARD_CHANGE=NO`
- `PTR9_CHANGE=NO`
- `PTR12_CHANGE=NO`
- `AUTHORITY_CHANGE=NO`

Replace only the incorrect serializer at the v4 artifact-audit hash boundary. Do not swallow the exception. Re-run the synthetic reasoning+visible-final path through artifact write and manifest validation. Two predecessor canary launchers contain the same stale expression; the narrow-fix task must perform a reachability check and either correct every still-reachable entrypoint or prove the sealed predecessors are unreachable, without rewriting historical evidence.

The launcher source SHA and every packet/approval binding derived from it will change. A successful fix therefore requires fresh materialization, fresh single-use approval, and a fresh nonce before any future real request. The fix can and must be validated offline first.
