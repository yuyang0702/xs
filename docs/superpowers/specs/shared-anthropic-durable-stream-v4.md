# Shared Anthropic response stream checkpoint contract

Status: implementation candidate; closure requires the V4 report gates.

`DurableAnthropicStreamV1` is the single owner of response progress, terminal identity,
storage acknowledgement and final response eligibility. `IncrementalSSEFramerV1`
retains exact byte boundaries; `AnthropicStream` retains existing validated semantic
rules. Storage callbacks cannot infer success from HTTP EOF or a boolean callback.
Requests, routing, caps, reasoning, narrative contracts and formal-write authority
remain outside this change.

The framer accepts LF, CRLF and CR. CR ends a line immediately; the next LF is
lexical continuation. Only a blank-line-closed frame reaches the decoder. Pending
bytes, including split UTF-8 sequences, survive checkpoint/reload. EOF before a
terminal with an unfinished frame is incomplete framing. Timeout/cancellation
before a terminal keeps the transport cause primary and partial framing secondary.
After a semantic terminal, unfinished suffix bytes are tail diagnostics. Complete
post-terminal semantic events retain the existing strict policy: ping is a
keepalive; an error is an explicit Provider error; other semantic events fail closed.
Closed frames validate all UTF-8 fields, including overwritten event metadata and
comments. A colonless field has an empty value, matching its colon-suffixed form.

The selected established patterns are an incremental state machine, deterministic
event journal, immutable signed checkpoint and atomic commit pointer. A general
EventSource client was not adopted: its reconnect behavior and event-only output
would not own this application's raw byte evidence or exact-once dispatch contract.
The existing semantic guards remain in use rather than importing a competing
protocol interpreter. The SSE framing standard is described by the
[HTML Standard](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream),
and semantic event shapes by [Claude streaming documentation](https://platform.claude.com/docs/en/build-with-claude/streaming).

Each checkpoint binds the owner, version, generation, previous checkpoint hash,
encoding, usage interpretation, durability requirement, raw/control journal,
framer state, raw/framed/semantic cursors and terminal/tail projection. Restore
reexecutes the same implementation and verifies the derived state. It grants no
network dispatch or new signing authority. A restored owner whose contract requires
durability cannot turn new unacknowledged bytes into a publishable terminal result.

The Full Short persistence port uses the existing external store and process-confined
Ed25519 signer. It binds execution, policy, physical attempt, exact outbound request
hash, route and capacity receipts. Under the existing lock it writes an immutable
signed sidecar, then atomically replaces the ledger's latest hash/generation. Only
then does it return `StreamDurableAckV1`. The explicit `STREAM_CHECKPOINT` ledger
transition can change only those two fields on the latest open attempt. Ordinary
mutations cannot change them. Reload verifies ledger seal and binding before reading
the signed checkpoint selected by that pointer. Orphans are never promoted by scanning.
This detects unauthorized file changes against retained anchors; it does not claim
to detect rollback of the entire external authority store by a storage administrator.

New storage uses a signed V2 suffix chain: each journal record is stored once, and
each generation has a compact state projection without repeated raw bytes or the
growing partial-line hex string. The selected chain reconstructs the exact V1 owner
checkpoint and runs semantic restoration once. Existing signed full V1 checkpoints
remain readable as chain bases. The factory's private submission closure binds its
one live owner and validates the exact pending checkpoint; its cache holds only
storage metadata and journal hashes, never a second reducer or terminal decision.
The public persistence function retains full semantic validation for untrusted
submissions. Retained evidence grows with raw bytes and checkpoint count. Full
checkpoint and journal-prefix hashing still scan history per commit; this change
does not claim linear total serialization CPU for arbitrarily tiny chunks.

An ambiguous storage transaction retains the identical pending checkpoint. Bounded
local confirmation can recover a lost ACK without creating a new physical request.
Later bytes and diagnostics are committed only after that generation is confirmed.
An unacknowledged suffix is not described as durable. Provider error provenance
survives storage failure. Capture/control failures are journal inputs so that live
and reloaded terminal classification agree.
Success and Provider-error identities have separate acknowledged durability flags.
If a later explicit error supersedes durable success, the earlier success ACK cannot
attest the new effective error. Error evidence remains incomplete until its own
checkpoint is acknowledged. Supported transport subclasses normalize to their
public timeout, cancellation or transport base category at the live boundary;
restart reproduces that category without serializing private exception messages.

Final protocol capture remains a single publication using the existing capture,
signature-anchor and usage-ledger path. The adapter closes the HTTP response before
that publication, so close faults already belong to the owner checkpoint. Full
Short obtains durability through the typed checkpoint port; legacy observers may
retain their existing one-capture callback behavior.

Migration is additive: existing ledgers without checkpoint fields and historical
raw captures are not rewritten. They retain their existing exact-capture replay
path. New streams create generation one and reject a second owner for the same
physical attempt. New readers validate optional checkpoint fields only where the
new checkpoint API is invoked. No private signing key is persisted to enable restart.
Rollback uses the pre-change source snapshot; existing raw captures and external
checkpoint evidence remain preserved.

Verification is recorded in the V4 report directory. It includes independent
semantic oracles, every registered framing pair, byte-boundary faults, all registered
persistable semantic states, actual Full Short observer/store/HTTP integration,
historical raw replay, request materialization parity and isolated full suites.
