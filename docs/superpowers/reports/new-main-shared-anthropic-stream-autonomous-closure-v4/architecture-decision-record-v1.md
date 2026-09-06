# Response stream ownership decision

The takeover found the core source unchanged from the sealed pre-V3 implementation.
V3 preserved eight investigations and a change contract, but did not implement an
incremental framer or a restorable durable owner. The old decoded transition tests
passed while four raw half-frame counterexamples failed.

The implementation keeps existing semantic validation and introduces one response
owner around it. The owner ingests chunks, feeds only closed frames to the decoder,
normalizes transport and capture controls separately, and commits signed checkpoints
through the production Full Short observer. The observer is a persistence port; it
does not independently classify terminal bytes or grant semantic success.

See the [versioned design](../../specs/shared-anthropic-durable-stream-v4.md) for
the contract, migration and rollback rules. This decision does not authorize request
changes. The external request parity proof compares 120 materializations per source
across all 15 configured Anthropic models and both transport policies.

Candidate 04 passed 940 isolated focused tests, including the real Full Short
observer/store/adapter chain. The original repository source and Git manifests were
unchanged throughout that suite. The next candidate adds explicit matrix-driven
coverage. Full-suite, final independent reviews and Strict L3 remain pending; this
record is not an architecture closure claim.
