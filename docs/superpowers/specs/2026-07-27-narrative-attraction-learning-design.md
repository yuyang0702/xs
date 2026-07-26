# Narrative Attraction Learning Design

## Goal

Turn any imported fiction reference into an evidence-backed narrative attraction map, then let a user-confirmed map guide the existing short-story causal chain and quality workflow. The purpose is stronger reader pull, not mechanical seven-beat compliance or imitation of source wording.

## Scope

This change extends the existing reference learning library and short-story workflow. It does not create another manuscript store, replace the outline, auto-adopt model conclusions, copy source names or plot packaging, or require every story to contain a conventional reversal.

The first production target is a 3,000-word short story created from an existing learning-library reference. Long fiction may consume confirmed mechanisms later, but this implementation does not impose a whole-novel seven-step chain on long projects.

## Core Model

The attraction map contains:

- `core_goal`: surface and emotional goals, each with evidence and confidence;
- `cycles`: repeatable obstacle, effort, result, state change, escalation, next question, evidence, and confidence;
- `accidents`: events that change the future situation;
- `reversal`: optional reinterpretation of prior events plus prior evidence;
- `ending`: surface payoff, emotional payoff, cost, and evidence;
- `opening`: immediate pressure, anomaly, reader question, future promise, and evidence;
- `question_chain`: question, opening evidence, answer evidence, and the next question;
- `relationship_arc`: before state, causing event, after state, and evidence;
- `fit`: `strong`, `partial`, or `not_applicable`, with an explanation;
- `uncertainties`: claims the available evidence cannot support.

All evidence uses absolute source offsets and excerpts. A missing semantic conclusion is represented as uncertainty, never filled with a keyword guess.

## Data Flow

1. The existing sentence-safe 3,000-5,000 character windows cover the complete source.
2. Deterministic local analysis emits opening, question, transition, decision, consequence, relationship, and payoff candidates. These are candidates only.
3. Optional LTP evidence enriches people, actions, semantic roles, and cross-window entity identity without making final literary judgments.
4. `reference_analysis` receives one source window plus its local candidates and returns evidenced events, state changes, questions, turns, relationship changes, and style evidence.
5. `reference_synthesis` receives compact claims and returns both reusable mechanisms and one attraction map. It must distinguish accident from reversal and may declare the seven-step fit partial or not applicable.
6. The attraction map is stored as a proposed learning node. The UI explains what was found, why it matters, where the evidence is, and what remains uncertain.
7. User confirmation is required before adoption. Adoption stores only abstract transfer guidance in the existing creative blueprint.
8. When a short project is planned, confirmed attraction guidance supplements the existing `short_causal_chain` contract. The new story still receives its own original goal, cycles, accident, reversal, and ending.
9. Draft and final review check state-changing cycles, question continuity, opening promise, relationship progression, reversal evidence, and ending payoff.

## Local Versus Model Responsibilities

Local code always handles complete coverage, offsets, evidence excerpts, keyword and punctuation signals, placement, cycle-count ranges, duplicate signatures, and presence of prior evidence. LTP may propose entity, action, and relationship links. Models handle implicit goals, emotional meaning, cross-window causal interpretation, genuine relationship change, accident-versus-reversal classification, and payoff quality.

If no API credential is available, local analysis remains usable and reports that semantic synthesis is unavailable. The UI must not present raw JSON parser errors or imply that a local candidate is a confirmed seven-step structure.

## Generation Rules

For a 3,000-word short story, the advisory range is two to three obstacle-effort-result cycles. Each cycle must change at least one of situation, knowledge, relationship, risk, cost, or available choice. A later cycle may echo an earlier one only when its state change and consequence differ.

The opening should establish at least three of immediate pressure, anomalous action, reader question, and concrete future promise. This is guidance rather than a hard blocker when the selected form intentionally uses a slower opening.

The ending must answer the surface goal, emotional goal, and cost. A reversal is valid only when it reinterprets prior evidence; a merely surprising event is recorded as an accident.

## Safety And Originality

Source names, settings, exact plot packaging, distinctive expressions, and long consecutive passages never enter generation constraints. Confirmed transfer guidance describes functions such as delayed explanation, escalating cost, or promise payoff. Existing originality checks remain the final safeguard.

## UI

The learning detail view adds a concise `剧情吸引力` section with plain-language cards for opening, goal, progress cycles, questions, relationship changes, reversal, ending, and uncertainty. Evidence is collapsed by default. The page shows local candidate status separately from model-synthesized and user-confirmed status.

Progress continues to use the existing task panel. Credential absence is reported before a paid analysis starts, naming the affected role and provider without exposing secrets.

## Error Handling

- Invalid or empty window output uses the configured fallback once.
- A failed window identifies its one-based index and preserves local results.
- Invalid synthesis preserves completed window claims.
- Missing API credentials fail before task dispatch with a readable provider message.
- Invalid attraction maps are saved only as claims, never as adoptable structures.
- A partial or non-applicable seven-step fit does not block reference learning or story generation.

## Verification

Automated tests must prove:

- full-source local candidates retain absolute evidence offsets;
- different wording can produce evidence without requiring literal seven-step labels;
- accident and reversal remain distinct;
- unsupported structure produces uncertainty rather than invented nodes;
- valid synthesized maps become proposed nodes;
- adopted guidance enters the creative blueprint without source packaging;
- a 3,000-word project requests two to three changing cycles;
- final review receives opening, question, relationship, reversal, and payoff checks;
- missing credentials produce an actionable error before a window task starts;
- the existing short-story and learning suites continue to pass.

The end-to-end acceptance artifact is one approximately 3,000-word original story generated through the normal project workflow from confirmed learning-library guidance, with a saved causal chain, final review, local full-text analysis, and originality report.
