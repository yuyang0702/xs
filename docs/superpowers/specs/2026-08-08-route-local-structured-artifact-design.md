# Route-local Structured Artifact and Runtime Authority Design

## Goal

Make provider-shaped output variation a presentation concern instead of a source of
workflow control drift. Runtime owns segment numbers, event ownership, ordering,
entry and exit boundaries, hashes, retry budgets, and checkpoint identity. A model
owns only the creative narrative fields named by the current artifact contract.

The design must work through OpenAI-compatible, Anthropic-compatible, Gemini-backed,
and other third-party gateways without inferring capability from a provider or model
brand. Existing checkpoints and legacy Markdown/JSON readers remain readable.

## Explicit route capability

Structured-output support is a property of one saved provider/model route. The
supported values are:

- `plain_text`: no native structured-output guarantee is assumed;
- `json_object`: the route can force a JSON object but not a closed schema;
- `strict_json_schema`: the route enforces the supplied closed JSON Schema;
- `strict_tool`: the route enforces one named tool call whose arguments match the
  supplied schema.

Ordinary or optional tool calling does not imply `strict_tool`. A route that rejects
forced `tool_choice` but later volunteers a tool call remains eligible for ordinary
tool workflows and is not eligible for a strict structured artifact.

Missing, `auto`, unrecognized, or brand-derived values resolve to `plain_text`.
Strict work never silently degrades to JSON-object mode. Primary and fallback routes
are evaluated independently, so a weak primary may fail over to an explicitly strict
fallback without sending unsupported parameters to the primary.

Capability probes use harmless, minimal payloads. A 404 or unsupported-endpoint
response is route-diagnostic evidence, not proof that the user's model does not
exist. Diagnosis checks the saved base URL, protocol adapter, `/v1` ownership, Chat
Completions versus Responses, Anthropic Messages, streaming requirements, and
gateway-specific headers before a route is classified. Probe success is persisted
only for that exact route and never changes role bindings automatically.

## Unified artifact contract

`StructuredArtifactContract` is closed and versioned. It supplies a provider schema
and documents the Runtime-owned authority excluded from model output. The gateway
selects native JSON Schema, forced tool arguments, JSON-object mode, or a safe plain
fallback from the route's explicit capability. Receipts record the selected mode and
route-local capability.

The planning presentation-repair contract contains only:

```json
{"events": [{"event_id": "EV-...", "narrative": "..."}]}
```

Runtime supplies the immutable expected event IDs and validates exact ordered
coverage. It then deterministically restores segment identity, outline basis,
opening, and handoff from the accepted current segment and re-enters the existing
complete planning validator. Unknown keys, duplicate or reordered IDs, ambiguous
wrappers, or incomplete narrative bodies remain invalid.

## Compatibility and recovery

Legacy canonical Markdown and previously accepted open provider wrappers remain
read-only-compatible. New native structured requests are used only when a route has
an explicit compatible capability. Otherwise Runtime uses the same reduced
model-owned payload contract in plain mode and validates it locally; no model-authored
field is promoted into machine control.

Capacity preflight, semantic packet splitting, bounded output-limit expansion,
monotonic repair, and hash-bound checkpoints continue to operate before promotion.
A presentation retry does not consume a semantic repair budget. Successful
normalization must cross the next authoritative planning boundary; safe rejection or
checkpoint retention alone is containment, not resolution.

## Rollback

Rollback is additive: set the affected route's capability to `plain_text` and the
gateway stops sending native structured parameters. Existing legacy readers and
checkpoints continue to work. No StoryState, manuscript, outline, run history, role
binding, secret, or formal project file is rewritten by capability migration or
probing.

## Acceptance coverage

Offline tests must cover at least six valid presentation shapes across four topology
classes, two unseen wrapper/nesting variants, two invalid or incomplete artifacts,
one output-limit fault, one transport/fallback fault, explicit third-party route
capability, and successful continuation through the next authoritative planning
boundary. Automated tests never call paid APIs. Separately authorized live probes
run only after offline gates pass and use no manuscript text.
