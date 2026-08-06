# Planning Adaptation V3 and Self-Recovering Model Workflow

## Outcome

The writing workflow must produce a validated final manuscript instead of merely detecting and containing model mistakes. Model creativity remains open inside presentation and scene realization, while formal plot direction, event ownership, causal state, viewpoint, promises, and ending remain stable.

The production incident used for acceptance is run `204415160b8f42fdb6d609851f1b81b9`. Its planning recovery reduced about 25 hard issues to four, then rejected candidates with 10 and 16 issues and stopped before causal-chain generation. V3 must preserve that safety behavior while making the next repair learn from rejected candidates and continue through final manuscript promotion.

## Authority model

Planning authority is separated into three layers:

1. **Local event realization** binds the formal event contracts, exact current plan segment, generation context, and Runtime-owned evidence. V3 does not bind mutable neighboring handoffs into an unchanged segment's local authority.
2. **Adjacent continuity** is represented by exact openings, handoffs, segment hashes, local receipt hashes, and ordered event IDs.
3. **Whole-story authority** binds the complete plan hash, all local receipts, formal event order, causality, knowledge and relationship progression, viewpoint/timeline, promises, and ending.

V1 and V2 ready artifacts remain readable through their original authority rules. New writers emit V3. A V2 boundary change still invalidates its neighbor's local receipt; a V3 boundary change leaves byte-identical local realization reusable and always reruns whole-story continuity review.

Unknown actor, viewpoint, location, time, knowledge, or relationship fields remain unknown. Runtime and prompts must not guess a second canon fact. Executor, intermediary, investigator, witness, collective, environment, institution, system, and hidden principal remain distinct unless formal evidence explicitly identifies them as the same entity.

## Monotonic recovery

`planning-best.md` and `planning-recovery-state.json` remain one hash-bound pair. Every candidate records:

- source and candidate plan hash;
- complete normalized issue records;
- introduced issue records and stable keys;
- actual changed segment IDs and before/after segment hashes;
- attributable, latent-baseline, resolved, retained, and newly discovered keys;
- comparison and acceptance decision.

A rejected candidate is diagnostic evidence only. It never becomes story authority. The next attempt starts from the current best plan and receives a segment-scoped no-regression projection of prior rejected evidence. Full records remain persisted; unrelated prose is represented by hashes and issue IDs so retry prompts cannot grow without bound.

The recovery ladder is:

1. replace only the smallest Runtime-owned evidence anchors cited by the current issue receipt;
2. if no valid anchor exists or a patch cannot preserve segment structure, rebuild only the affected complete formal segment;
3. reject any candidate that does not strictly shrink the stable hard-issue set or introduces a new hard issue, restoring the prior best plan.

Every accepted mutation re-enters local structure, local semantic review, adjacent continuity, and whole-story review. Any plan mutation invalidates an older causal chain.

### Change-owned issue attribution

Model reviews are nondeterministic and can reveal an old defect in an unchanged
segment only after another segment has been repaired. Candidate comparison therefore
uses the best-plan and candidate segment hashes as mutation authority. A finding is
attributable to the candidate when it belongs to an actually changed segment, has no
safe segment scope, or is a boundary/whole-story finding whose affected segment set
intersects the changed scope. Only that attributable set participates in the
strict-improvement and no-new-hard-issue decision.

A finding owned wholly by a byte-identical segment is a latent baseline issue. It is
not treated as introduced by the current candidate, but it is not ignored: Runtime
merges it into the latest best issue ledger and schedules that segment as a later
independent recovery unit. Previously known issues on unchanged segments are retained
even if a later review omits them. This prevents both collateral rollback and false
resolution caused by reviewer variance. Unauthorized segment changes and new
changed/adjacent boundary findings remain hard rejections. Promotion still requires
complete-plan reassembly plus adjacent and whole-plan authorization, so granular
retention cannot create an incoherent mixed plan.

### Repair-anchor granularity

Review evidence is an audit binding, not permission to replace an arbitrary amount of plan text. Before a targeted repair, Runtime deterministically projects a broad evidence ID to the smallest nested candidate that keeps the same event-ID set, contains no Markdown heading, and retains enough semantic body to represent the event execution. A bare label or one sentence is not sufficient. If no safe nested candidate exists, the original evidence remains bound and the complete-segment rebuild ladder owns recovery. Every applied patch is rechecked for event-body retention, event coverage, required fields, adjacent handoffs, and whole-plan integrity. A candidate that fixes viewpoint or actor wording by deleting the event's action, reaction, or result is rejected and never enters the best-plan ledger.

### Composite-event completion obligations

A formal event may contain several independently required reactions or a dialogue pair whose response creates an exit-state or relationship promise. Passing the whole source block as one free-form contract is insufficient because a model can realize the first participant and silently omit a later responder. Runtime therefore projects the confirmed outline into a hash-stable event completion checklist. Every item retains its exact event-owned source excerpt, explicit participants, and genre-neutral work kinds (`action`, `reaction`, `outcome`, `commitment`). The projection never infers an unnamed participant or creates new canon.

Before semantic model review, Runtime applies a narrow deterministic precheck only when the confirmed event contains at least two participants with stable identity forms. Natural pronouns in single-participant events remain valid; role or kinship titles can be realized through a confirmed name or natural form of address and remain under semantic review. Literary quality is still judged semantically rather than by keyword. A missing stable participant produces a segment-owned hard issue whose invariant set reflects the omitted work. Commitment omissions additionally bind exit state, relationship state, and promise/ending authority. Compatible semantic issues already persisted for the exact plan hash are retained so the deterministic fast path cannot hide another known problem.

This failure goes directly to complete-segment rebuild because absent prose has no safe evidence anchor to patch. The repair call receives the exact current segment, formal contracts, compact checklist, adjacent accepted boundaries, and only segment-relevant rejected-candidate evidence. Checklist size is bounded by current semantic ownership; full authority remains persisted and nothing is mechanically truncated. A candidate is incomplete until every explicitly required participant is present. Once complete, it must still pass normal local semantic receipts, adjacent handoffs, and whole-plan adjudication. Other segments are reconstructed from their previous exact bytes, so granularity does not become collateral rollback. The same contract applies across genres and ensemble casts because it follows explicit names and event ownership rather than novel-specific role labels.

### Narrator contract

First-person projects persist a project-scoped narrator contract (`mode`, narrator character ID/name, and self-reference) resolved from explicit metadata, an unambiguous outline declaration, or one unique narrator/protagonist. The contract is carried through draft segmentation, retries, resumes, polish, targeted/manual revision, AI re-review, and final review. Multiple plausible narrators are a hard confirmation boundary; Runtime must stop before generation and ask the user rather than silently selecting one. The contract constrains viewpoint and self-reference only; dialogue, description, pacing, humor, and scene realization remain creative space.

## Token and provider capacity

Complete authority and failure evidence are persisted losslessly, but a model call receives only the complete semantic ownership required by that call. Recovery evidence is projected by segment and stable issue identity. When raw rejected-plan excerpts approach the packet budget, Runtime retains exact hashes and every machine-relevant issue dimension rather than repeating rejected prose.

Whole-plan review estimates provider context pressure. It uses, in order:

1. full formal contracts, segment receipts, and accepted plan;
2. a full-coverage structural map containing every segment, event, opening, handoff, local receipt hash, invariant, and selected evidence;
3. a hierarchical structural map using evidence hashes after local exact-prose review;
4. a complete coverage manifest using formal contract hashes, ordered event IDs, openings, handoffs, and local receipt hashes.

Unknown provider limits use a conservative 32K context assumption. Context mitigation changes call topology or deterministic representation, never the story target, event ownership, required output length, formal authority, or final quality threshold. Output truncation, transport failure, and cancellation retain completed packets and the current best artifact for resume.

Segment review is also capacity-aware. A preflight `compact` or `split` decision is an orchestration request, not a terminal failure. Runtime recursively partitions the affected segment by contiguous formal-event ownership and binds every packet to the immutable full-segment authority plus its ordered event IDs. Transport input contains only exact blocks owned by the packet while retaining the parent evidence IDs, dependency index, adjacent handoffs, and full authority hashes. The merged receipt must reproduce the original ordered event coverage and pass the unchanged full-segment validator before whole-plan review. Successful packet receipts are persisted as hash-bound checkpoints and reused across compatible failed runs; ambiguous or stale receipts are regenerated.

A formal event remains indivisible as narrative ownership, but not as validation topology. If its complete review packet is still too large, Runtime obtains three hash-bound facet receipts covering all formal invariants: function/agency/dependencies, state transitions, and continuity/viewpoint/ending promises. If a facet still cannot fit, Runtime reviews paragraph-aligned overlapping exact-plan windows. Window envelopes bind the facet authority, character range, exact text hash, source evidence IDs, and verdicts. Deterministic merge requires full gapless range coverage, permits overlap but not omitted ownership, ANDs every invariant across all windows, retains every changed dimension and evidence identity, and then reruns the event, parent segment, adjacent boundary, and whole-plan validators. Window, facet, and packet checkpoints support interruption and cross-task resume; conflicting hashes force regeneration instead of choosing one result.

Production run `dd0d6d2d981b4316a0c81d901bd38dc1` is the capacity regression fixture: the Review route had no declared capacity, so Runtime used 32,768 tokens; segment 1 owned seven of 29 formal events; its estimated 24,143 input tokens plus 7,394 output-reserve tokens produced the previously terminal 31,537-token preflight. Acceptance requires that this shape perform event-owned packet review, lossless merge, and continuation to whole-plan review without calling the oversized parent request.

Production run `e86225d9d6664243b4d8c4e45295144f` is the singleton-topology fixture. Reducing seven events to one previously changed estimated input only from 24,143 to 23,146 tokens because the full parent plan and global authority were repeated. Acceptance requires exact event projection, bounded protocol reserve, facet/window recovery when necessary, and a successful offline continuation through causal chain, execution manifest, every draft segment, merge, polish, AI issue refresh, terminal review, formal manuscript promotion, and targeted/manual revision compatibility.

Production run `d785dd5c711c4bc785caec10977cf6bb` is the targeted-repair capacity fixture. Its six-segment, 29-event review had already completed through semantic splitting, but the next evidence-patch call inherited the complete `planning` stage's 12,288-token output reserve. With 20,407 estimated input tokens and 18,514 authority tokens, preflight incorrectly required 32,695 tokens in a 32,768-token route and terminated recovery. A closed JSON evidence patch now declares a bounded protocol-output contract sized from the exact authorized anchors plus protocol overhead, not from the complete segment; a complete formal-segment rebuild declares a scope-aware creative contract derived from that segment's expected output rather than the whole planning floor. The route preflight reserves the larger independently computed primary/fallback value, and the actual fallback call keeps the same contract. This changes only capacity topology and initial headroom: it never shortens the requested segment, and an output-limit response still expands headroom or moves to a smaller semantic scope. If capacity or transport still rejects one candidate, the best complete plan and issue ledger remain reusable and the recovery loop continues within its bounded attempts.

Production run `9946d29b04fc4fe2970af117b084c8e9` adds the complete-rebuild capacity boundary. The deterministic completion checklist correctly found that segment 5's `EV-BEAE4985` omitted the required Pei Yanxing response, but rebuilding all four segment events in one request required 25,260 input-plus-output-reserve tokens on the conservative 32,768-token route and stopped before a provider call. Acceptance requires recursive contiguous event-owned creative packets, exact numbered/list-body projection without sibling event prose, predecessor hash binding, hash-bound leaf checkpoints, lossless ordered merge, and the unchanged complete-segment validator. The recovered candidate must then pass local segment review, adjacent handoffs, and whole-plan review before causal-chain generation. Unaffected segments remain byte-identical, and later polish or targeted/manual revision continues to use the same narrative-integrity closure rather than trusting the split merely because its leaves completed.

## Creativity and quality

The workflow does not prescribe one acceptable rendering. Dialogue, description, emotional texture, humor, scene rhythm, trigger method, evidence-acquisition method, supporting participants, local setting, and non-dependent micro-order remain open creative space.

A structural repair is not accepted merely because it removes a hard issue. It must preserve useful voice, dialogue, detail, pacing, and reasonable length. Downstream draft, polish, targeted repair, user-selected repair, AI re-review, and final review continue using the existing hash-bound narrative-integrity gates. Any mutation that damages atomic beats, actor/action identity, viewpoint, time/location/knowledge state, entry/exit state, event order, promises, or ending restores the last accepted complete scope and retries with a smaller authorized mutation.

The reader-visible manuscript never carries Runtime's internal segment sentinel. A passed polish/revision integrity envelope therefore records a clean-publication SHA-256, the exact ordered character lengths of all formal segments, each segment's text and predecessor hash, and the execution-manifest binding. Runtime may reconstruct segment authority from a clean candidate only when those lengths reproduce every stored segment hash and rejoin byte-for-byte to the protected publication. Targeted and manual revision preserve those boundaries, revalidate changed segments and the whole story, and emit a new envelope rather than copying stale hashes or receipts. Historical envelopes without publication lengths remain readable only when a hash-matching segmented draft or polish artifact can reconstruct the same clean publication losslessly.

## Compatibility and rollback

- No SQLite migration and no second StoryState are introduced.
- Formal outlines, existing manuscripts, project materials, model bindings, and run history are not rewritten.
- V1/V2 artifacts remain readable; failed older plans are untrusted recovery inputs reviewed under V3.
- Recovery state version 1 gains optional fields and remains backward compatible.
- Older recovery envelopes without change-attribution fields keep their historical
  global-comparison behavior until the next current-code review reconstructs hashes
  and a complete issue ledger; no destructive migration is required.
- Cross-task resume copies the complete hash-bound best plan and rejected-candidate ledger into the new run.
- If a complete-segment rebuild fixes one invariant but introduces another, that same
  failing unit may receive one second bounded rebuild attempt from the latest best
  plan and the first rebuild's complete failure evidence. The attempt never widens
  to an unrelated segment or whole-plan rewrite; successful units remain checkpointed.
- Code rollback can ignore V3 diagnostics without deleting project content. A rollback must not promote a V3 candidate that lacks a valid older authority chain.

## Acceptance

Focused and complete regression suites must pass without paid model calls. Required cases include:

- the production-shaped `25 → 4 → 10 rejected → 16 rejected` ledger;
- production run `62859567...`: repairing segment 2 must retain that byte-exact
  improvement when the next review first exposes latent segment-3 issues, then repair
  segment 3 as an independent unit; a new `[2, 3]` boundary issue must still reject;
- evidence patch authorization and byte preservation outside anchors;
- production run `9946d29b...`: the `EV-BEAE4985` composite reaction must detect the omitted responder before model review, rebuild only segment 5 from its explicit action/reaction/outcome/commitment checklist, retain all other segment bytes, and then pass local, adjacent, and whole-plan review;
- rejected-candidate feedback starts from the best plan and prevents recurrence;
- segment-scoped and token-bounded recovery feedback;
- the `dd0d6d2d...` seven-event segment preflight, event-owned packet merge, interruption checkpoint reuse, and continuation to whole-plan review;
- the `e86225d9...` singleton projection, all-invariant facet coverage, complete overlapping windows, conflicting/missing checkpoint rejection, and full offline business-flow continuation;
- the `d785dd5c...` targeted-patch reserve, scope-aware complete-segment rebuild, identical primary/fallback capacity contract, candidate-level preflight recovery, and full offline business-flow continuation;
- V2 boundary behavior, V3 local reuse, and V1/V2 artifact compatibility;
- interruption and cross-task resume with the complete failure ledger;
- unknown fields, non-person executors, ensemble/multi-viewpoint, and non-linear timelines;
- successful continuation through causal chain, execution manifest, all draft segments, merge, polish, targeted/manual-repair compatibility, AI re-review refresh, final review, and final manuscript promotion.

After offline acceptance, one authorized real-provider run may use the current project and provider configuration. It must run once through the complete business workflow, keep the result as a candidate until final review passes, and record stage calls, token use, recovery attempts, regressions, and final artifact hashes.
