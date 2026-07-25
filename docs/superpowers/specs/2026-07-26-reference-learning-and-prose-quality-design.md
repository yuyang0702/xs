# Reference Learning Library and Prose Quality Design

## Purpose

Add a reusable reference-learning system that extracts evidenced narrative mechanisms from user-provided texts, recommends compatible mechanisms to a story project, and turns confirmed recommendations into better outlines, scene briefs, and prose revisions.

The feature must extend the existing planning, drafting, review, candidate, and project-material flows. It must not create a second outline generator, a second authoritative story state, or a direct write path to formal manuscripts.

## Confirmed Product Decisions

- Use a two-layer library: global reference analysis plus project-scoped adoption.
- Recommend mechanisms automatically, but require user confirmation before they affect a project.
- Accept pasted text, TXT, DOCX, PDF, and ordinary public HTTP/HTTPS pages.
- Preserve imported source text locally for evidence review and reanalysis.
- Analyze universal narrative mechanisms first, then evaluate platform-specific suitability.
- Preserve model analysis as read-only; store user corrections as separate revisions that take precedence.
- Support both new projects and candidate outline versions for existing projects.
- Use a typed knowledge graph, initially persisted in the existing SQLite database.
- Borrow Graphiti's temporal/provenance model and LightRAG's graph retrieval pattern without adopting either framework wholesale.
- Offer enhanced Chinese NLP as an optional local backend installed and enabled explicitly from Settings.
- Prefer deterministic local editorial checks before neural NLP or provider calls.
- Do not deploy or manage a local generative language model; creative generation continues through configured remote providers.
- Activate completed learning and quality stages directly after their acceptance tests pass; do not add a separate shadow-mode product state.
- Do not implement model fine-tuning, automatic project mutation, graph database services, or machine-learning ranking in the first release.

## Non-Goals

- Predicting whether a work will become popular or pass platform review.
- Reproducing a reference author's distinctive expression, characters, settings, or plot sequence.
- Bypassing login, paywalls, CAPTCHAs, anti-bot controls, or access restrictions.
- OCR for scanned PDFs in the first release.
- Automatically rewriting formal outlines, project materials, or manuscripts.
- Replacing StoryState, project files, existing role bindings, Skills, or Runtime validation.
- Downloading or loading local NLP models without an explicit user action.
- Installing Ollama, llama.cpp, vLLM, or local generative-model runtimes.

## Architecture

The system is one evidence-to-writing pipeline:

1. Import and normalize a reference source.
2. Calculate deterministic prose metrics locally.
3. Analyze paragraph-aligned windows with source locations.
4. Reconcile window results into a story map.
5. Derive evidenced, content-independent narrative mechanisms.
6. Store sources, claims, evidence, and temporal relationships in the global learning graph.
7. Retrieve and rank mechanisms against a project's platform, genre, length, characters, outline, and constraints.
8. Let the user adopt, edit, or reject recommendations.
9. Save confirmed choices as a project creative blueprint and executable prose baseline.
10. Send only the confirmed blueprint and necessary project evidence through the existing planning route.
11. Build scene briefs from the accepted outline and use the existing draft route.
12. Diagnose prose locally and with a narrow editorial pass, then run targeted line edits through the existing candidate and validation flow.
13. Record adoption and revision outcomes for later recommendation improvements.

## Authority and Data Ownership

StoryState and current project materials remain authoritative for story facts. The learning graph is authoritative only for imported sources, analysis provenance, and user-confirmed learning annotations.

The system distinguishes:

- `source`: immutable imported text version and metadata;
- `model_claim`: immutable model-produced analysis;
- `user_revision`: versioned correction, confirmation, rejection, merge, or note;
- `mechanism`: reusable content-independent narrative technique;
- `project_adoption`: a project-scoped decision to use or reject a mechanism;
- `creative_blueprint`: an editable project candidate derived from confirmed adoptions;
- `prose_baseline`: executable project writing constraints;
- `scene_brief`: derived scene-level writing instructions;
- `formal_material`: existing authoritative project data, changed only through the current candidate/confirm flow.

Deleting or reanalyzing a source never silently changes a project. Existing project adoptions keep a provenance tombstone and become reviewable when their source disappears or materially changes.

## Knowledge Graph

### Global Learning Graph

Initial node types:

- reference source and source version;
- source window and evidence span;
- event and character-state transition;
- setup, payoff, reveal, reversal, conflict, and reader question;
- narrative mechanism;
- style characteristic;
- emotional effect;
- platform, genre, length band, and narrative viewpoint;
- model claim and user revision.

Initial edge types include `contains`, `supports`, `uses`, `abstracts_to`, `causes`, `prepares`, `pays_off`, `appears_at`, `fits`, `conflicts_with`, `supersedes`, and `rejected_by`.

Every model-created node or relationship records source evidence, source offsets, run and model identity, analysis version, confidence, and review state. Unsupported claims remain proposals and cannot become high-confidence recommendations.

### Project Narrative Graph

Project nodes include characters, locations, objects, events, goals, secrets, relationships, knowledge states, setups, payoffs, outline beats, scene briefs, blueprint rules, and prose rules.

Edges may carry story-time and system-time validity. This permits a relationship or belief to be true during one chapter range and invalid later without deleting history.

The project graph is a derived index over authoritative materials. It detects dependencies and impact; it does not bypass current material edit and confirmation APIs.

### Storage

Use typed SQLite tables for graph nodes, edges, evidence, revisions, and project adoptions. Keep IDs stable and use ordinary indexes for type, source, project, status, and validity fields. Add recursive traversal only for bounded impact and provenance queries.

Do not require Neo4j, FalkorDB, Kuzu, embeddings, or a background graph service. NetworkX may be added later only if a measured need for community or path algorithms appears.

## Local Editorial and NLP Layers

Analysis uses a cost and complexity ladder:

1. standard-library rules and project dictionaries;
2. optional lightweight tokenization where measured value justifies it;
3. optional neural Chinese NLP installed by the user;
4. remote language-model analysis only for unresolved semantic work.

### Local Editorial Engine

The standard-library engine detects exact and n-gram repetition, repeated functional phrases, nearby action and body-reaction reuse, sentence-length regularity, repeated sentence signatures, one-sentence paragraph runs, mechanical dialogue alternation, punctuation patterns, and project-specific forbidden expressions.

Rules have stable IDs, evidence locations, severity, applicability, and a repair objective. Project baselines calibrate thresholds; a single universal sentence-length target must not flatten different story voices.

### Optional Chinese NLP Backend

Settings exposes an explicit install action with download size, disk requirement, model license, expected CPU behavior, and uninstall controls. The application never downloads a model during ordinary startup or workflow execution.

The backend is lazy-loaded on first enabled analysis, runs locally, caches results by text and model-version hash, and releases resources when practical. Failure, absence, or incompatibility falls back to the standard-library engine without blocking planning, drafting, or existing projects.

The target workstation has an Intel Core i5-11320H, 16 GB RAM, Intel Iris Xe integrated graphics, and no CUDA-capable GPU. Neural NLP therefore runs as a CPU workload with one analysis job at a time. It must not remain resident in the FastAPI process: a bounded worker process loads the selected NLP model on demand and exits after work or an idle timeout so memory is returned to the operating system. Large local embedding models such as BGE-M3 are excluded from the initial delivery.

Before choosing HanLP or LTP, evaluate both outside the production dependency set against a fixed Chinese-fiction corpus containing modern and historical language, omitted subjects, titles, pronouns, negated actions, dialogue attribution, and multi-action sentences. Adopt one backend only if it materially improves entity, semantic-role, and dependency evidence at acceptable Windows CPU, memory, startup, package-size, and license cost.

Neural NLP may propose entities, actions, semantic roles, dependency signatures, pronoun ambiguity, and dialogue attribution. It does not edit prose or become authoritative story state.

### Character Epistemic State

Project narrative edges distinguish observed, reported, inferred, doubted, denied, misunderstood, and confirmed knowledge. A character's expression and decision may not use certainty unavailable at that story position.

The prose system does not add random hedges or mistakes to appear human. It derives uncertainty from available evidence, character experience, pressure, bias, and consequences. Local checks flag unjustified certainty; semantic resolution and revision remain bounded model tasks when rules cannot decide.

### Quality Regression Corpus

Store project-independent, anonymized examples of confirmed prose failures and expected diagnostic classes. Initial classes include checklist judgment, fragmented conclusions, mechanical dialogue, repeated body reactions, duplicated semantic statements, overprecise cognition, identical character voices, and unsupported emotional summaries.

Rule, Skill, routing, and prompt changes run against this corpus without paid API calls. Provider-dependent comparative evaluation is manual and separately authorized.

## Analysis Pipeline

### Import

- Normalize and hash extracted text.
- Deduplicate identical source versions before any model call.
- Preserve headings, paragraphs, and stable character offsets.
- Store extractor warnings and extraction quality.
- Reject empty, oversized, unsupported, or unsafe input explicitly.

URL fetching allows only public HTTP/HTTPS destinations. It rejects local, loopback, private, link-local, metadata-service, and non-HTTP addresses before and after redirects. It limits redirects, response size, content type, and request duration. Imported page content is untrusted data and cannot override model or application instructions.

### Deterministic Metrics

Calculate sentence and paragraph distributions, dialogue ratio, dialogue runs, one-sentence paragraph runs, punctuation patterns, chapter lengths, and available structural positions before model analysis.

### Window Analysis

Split long text into paragraph-aligned 4,000-6,000 character windows with bounded overlap. Each window returns structured events, goals, obstacles, information changes, risk changes, relationship changes, reader questions, turning points, style evidence, and source spans. It does not assign a final score.

Use source hashes and window hashes for resumable checkpoints. A failed window retries or falls back independently; unchanged successful windows are reused.

### Reconciliation and Abstraction

Reconcile entities and ordered events across windows before deriving mechanisms. The abstraction pass removes names, proprietary setting details, distinctive lines, and concrete plot packaging.

A reusable mechanism must describe:

- trigger conditions;
- structural position or range;
- character or reader-state change;
- intended emotional effect;
- required preparation;
- downstream consequence;
- evidence and confidence;
- incompatible project conditions.

The UI must show fact, interpretation, and transfer guidance separately.

## Recommendation and Project Adoption

Local filtering first considers platform, genre, length, viewpoint, emotional target, existing mechanisms, confirmed character constraints, and explicit user rejections. A model receives only the bounded project summary and shortlisted candidates when semantic suitability requires judgment.

Recommendations display evidence, intended effect, suggested position, compatibility reasons, conflicts, and copying risk. The user may adopt, edit, reject, or defer each mechanism.

Confirmed choices produce a project creative blueprint. The blueprint is editable and versioned. Planning produces a candidate outline version and a difference/conflict report; it never overwrites the current outline.

## Prose Quality Integration

### Executable Prose Baseline

Convert confirmed style learning and user preferences into measurable or reviewable constraints: viewpoint and narrative distance, sentence and paragraph rhythm, dialogue behavior, psychology presentation, action/sensation integration, professional-detail presentation, and forbidden prose patterns.

Generic labels such as "delicate" or "natural" are not executable rules and must be converted into concrete guidance before adoption.

### Character Voice Profiles

Each principal character may have a versioned voice profile containing vocabulary, sentence behavior, pressure response, emotional directness, forms of address, habitual actions, and prohibited expressions. Only profiles for characters present in the current scene are loaded.

### Scene Briefs

Build editable `scene-NN` briefs from the accepted outline. Each brief specifies viewpoint, entry goal, obstacle, relationship tension, required state change, information boundary, reader question, exit state, locked facts, and relevant prose constraints.

Drafting continues through the existing draft role, one complete scene at a time where the workflow permits. Existing behavior remains available when the feature is disabled.

### Line Edit

Add a narrow `line_edit` stage after diagnosis. It handles fragmented judgment chains, checklist prose, mechanical question-answer dialogue, repeated syntax, overexplained psychology, disconnected action and dialogue, narrative-distance drift, and character-voice violations.

It may not alter event order, locked facts, scene count, character decisions, setups, payoffs, or ending constraints. It receives the source passage, small adjacent context, one or more evidenced issues, relevant voice profiles, and the prose baseline.

Candidates pass existing fact, length, prose-quality, typography, and local acceptance checks. Rejected candidates preserve source text. High-risk passages may request two materially different candidates; identical retry prompts are not repeated indefinitely.

## Change Propagation

When authoritative character or world material changes:

1. Update the authoritative material through the existing revision flow.
2. Mark superseded graph facts without deleting their history.
3. Traverse bounded dependency edges to identify affected voice profiles, blueprint rules, outline beats, scene briefs, setups, payoffs, and candidate prose.
4. Produce an impact report with evidence and severity.
5. Rebuild unedited derived artifacts only after one user confirmation.
6. Produce candidate alternatives for user-edited or formal artifacts.
7. Never rewrite formal manuscript text automatically.

Global reference sources and analyses are not changed by project-material edits. Only project suitability and adoption status may become stale or require review.

## API and Model Routing

The library remains local. Provider APIs receive only task-bounded data:

- source analysis: one source window, local metrics, and bounded prior state;
- synthesis: structured window results and selected evidence;
- recommendation: project summary and a small candidate set;
- planning: confirmed creative blueprint and necessary authoritative project material;
- drafting: one scene brief and relevant project context;
- line editing: one passage, issue evidence, prose baseline, and relevant voice profiles.

Add explicit role bindings for `reference_analysis`, `reference_synthesis`, and `line_edit`, with visible configured fallbacks. Recommendation and outline generation continue through planning; final checks continue through review/final_review. No new provider protocol, credential store, or independent model client is introduced.

Reference analysis does not need StoryToolbox. Project recommendation, planning, drafting, and review may query the existing read-only toolbox. Models cannot modify graph or project state through tools.

## User Interface

Add a top-level `学习库` menu with:

- reference sources;
- analysis reports;
- mechanism graph;
- user revisions;
- source versions and provenance.

Add project-material sections for:

- creative blueprint;
- project prose baseline;
- adopted mechanisms;
- character voice profiles inside character records;
- scene briefs under plot structure;
- impact and versions as an advanced, collapsed section.

Global raw source text, complete evidence, unadopted mechanisms, and other projects' adoption state remain in the learning library. Project pages show only confirmed project-scoped material and provenance links.

## Machine Learning Readiness

The first release records recommendation impressions, adoption, rejection, user correction, outline retention, accepted line edits, and final artifact retention. It does not train a model.

After sufficient real feedback exists, optional local features may add similarity clustering, duplicate-mechanism suggestions, reference recommendation, and lightweight learning-to-rank. These features remain advisory and must not mutate authoritative data.

## Migration and Rollback

- Existing projects remain unchanged and the feature is disabled until used.
- Database migration is additive and idempotent.
- Create a verified database backup before schema migration.
- No existing project file is rewritten during migration.
- Disabling the feature restores the current planning/drafting path without deleting learning data.
- Removing a source preserves project adoption tombstones and never changes existing outlines or manuscripts.

## Delivery Plan

### Phase 1: Foundation and Import

Add additive SQLite schema, safe source import, local source storage, deduplication, extraction diagnostics, and CRUD/version APIs. Support pasted text and TXT first, then DOCX, PDF, and safe public URLs.

Acceptance: imports are local, deduplicated, versioned, safely bounded, and deletable without changing projects.

### Phase 2: Local Editorial Engine and NLP Evaluation

Add the rule registry, project-calibrated prose metrics, sentence signatures, repetition diagnostics, quality regression corpus, NLP backend interface, Settings install/uninstall controls, model-version cache, and fail-open fallback. Benchmark HanLP and LTP on the approved Chinese-fiction corpus before selecting at most one production backend.

Acceptance: all baseline diagnostics run without provider calls; no model downloads without an explicit Settings action; disabling or uninstalling NLP preserves existing workflows; the selected backend demonstrates recorded quality and resource gains over rules alone.

### Phase 3: Evidence Analysis and Learning Graph

Add deterministic metrics, resumable window analysis, reconciliation, mechanism abstraction, provenance, user revisions, and learning-library report pages.

Acceptance: every usable mechanism has traceable evidence; interrupted analysis resumes unchanged windows; unsupported claims cannot become confirmed automatically.

### Phase 4: Recommendation and Creative Blueprint

Add project matching, recommendation review, project adoptions, editable blueprints, candidate outline generation, conflict checks, and outline differences.

Acceptance: no recommendation affects a project before confirmation; existing outlines are never overwritten; disabling the feature uses the old planning path.

### Phase 5: Prose Baseline, Voice, Epistemic State, and Scene Briefs

Add executable prose baselines, character voice profiles, observed/reported/inferred/doubted knowledge states, scene-brief generation/editing, and bounded context assembly for draft.

Acceptance: the active rules and source are visible; character-material changes produce impact reports; characters do not express unjustified certainty from unavailable information; existing draft behavior remains tested as fallback.

### Phase 6: Diagnostic Line Edit

Add evidenced prose diagnostics, the `line_edit` role, targeted candidate generation, local acceptance, resumable checkpoints, and candidate comparisons.

Acceptance: no formal manuscript is modified automatically; targeted edits preserve locked facts and do not regress deterministic prose checks.

### Phase 7: Feedback and Evaluation

Record recommendation and revision outcomes, add evidence coverage and human confirmation metrics, and compare enabled projects against the preserved baseline path.

Acceptance: metrics are descriptive rather than popularity predictions; no machine-learning dependency is added without sufficient data and a separate approved design.

## Verification

Each phase requires focused tests followed by the full suite. Required coverage includes:

- idempotent schema migration and rollback-safe backup;
- source deduplication, extraction failure, size limits, redirect validation, and SSRF prevention;
- prompt-injection content remaining inert source data;
- local editorial rule IDs, evidence locations, project calibration, and regression-corpus stability;
- explicit NLP installation, lazy loading, versioned cache, uninstall, and rule-only fallback;
- stable source offsets and provenance;
- resumable window checkpoints and provider fallback;
- graph revision, supersession, bounded traversal, and deletion tombstones;
- recommendation confirmation gates and project isolation;
- candidate-only outline and prose writes;
- character-change impact without automatic formal mutation;
- character knowledge certainty matching observed, reported, inferred, doubted, and confirmed state;
- line-edit fact preservation and deterministic quality checks;
- existing projects, credentials, role bindings, Skills, formal manuscripts, and run history remaining unchanged.

No automated test may call paid provider APIs.
