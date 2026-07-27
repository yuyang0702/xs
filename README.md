# Novel Flywheel Console

## 本地全文分析与增量终审

作品可以单独启用“正文全文分析与增量终审”。启用后，程序在草稿完成、初次润色、每轮返修和发布前对完整正文执行确定性规则扫描，并在全局 LTP 已启用时复用独立 CPU 进程和版本化缓存提取人物、事件与语义角色证据。

`review` 和 `reader_review` 仍读取标注抽样片段；`review` 额外接收有长度上限的全文本地摘要。首次 `final_review` 仍覆盖全部正文。首次终审未通过并发生返修时，系统复核改动窗口、相邻窗口及人物/事件关联窗口；修改超过正文 20%、影响超过 40% 的窗口，或涉及事件顺序、开头承诺、高潮、结尾、时间线、因果，或 LTP/窗口映射不可靠时，自动恢复全文终审。

原创候选只与本地项目稿件和导入参考资料比较，包括连续相似片段、人名近似、设定、关键情节和独特表达候选，不代表全网查重或法律结论。模型和 LTP 均不能直接覆盖正式稿；候选哈希、本地全文扫描和终审哈希一致后才允许发布。

Local multi-model writing workflow for short stories and long serial novels.

## Start

Run `start-novel-console.cmd`, then open `http://127.0.0.1:8765`.

## Model tools

Existing providers can be edited or deleted from **模型与 API**. Editing changes the visible name, protocol, and Base URL while preserving internal headers and timeout settings. A blank API Key keeps the current secret; entering a new key replaces it in the system credential store. Deleting a provider also deletes its model mappings. Primary role bindings using that provider are removed, while fallback references are cleared without removing the primary binding.

Each model mapping has a Tool Calling mode:

- `auto`: try native tool calling and fall back to an injected evidence package only when the provider explicitly rejects tools.
- `enabled`: require native tool calling and fail the stage if the provider rejects it.
- `disabled`: always use the injected evidence package.

Capability detection forces the provider to call a dedicated probe tool. OpenAI Chat and Anthropic requests both serialize the matching `tool_choice`. Thinking models that explicitly reject forced tool choice are retried once with normal tool selection. If a relay still ignores or strips the tool request, the result reports that no `probe_tool` call was returned instead of showing an unexplained failure.

Anthropic, OpenAI Chat, and OpenAI Responses adapters receive provider output as streams and aggregate it behind the existing response interface. The browser and workflow stages still receive complete responses; streaming keeps long generations active without requiring UI changes. Relays that reject optional stream parameters or streaming itself use compatibility fallbacks automatically.

Character material edits can retire removed settings and trigger a linked-material analysis through the configured `maintenance` role. The analysis only proposes exact, local patches to project materials such as plot arcs, timelines, promises, and constraints. It never changes manuscript prose. The user selects which proposals to apply; target hashes, project-relative paths, snapshots, and StoryState revisions prevent stale or partial updates.

Models can only use these project-scoped read tools:

- search prior chapters;
- read a bounded part of a numbered chapter;
- query canon and current character state;
- query foreshadowing, timeline, volume plans, and unresolved drift.

Models cannot pass file paths, write project files, or run commands. Each stage allows at most eight tool rounds. The deterministic flywheel remains the only writer of formal files and retains snapshots and rollback.

## Skills

Skills are scanned again for every stage. Global Skills are loaded from the configured roots, and project-specific Skills can be added under:

```text
<project>/.agents/skills/<skill-name>/SKILL.md
```

A project Skill with the same name overrides the global version on the next run; no server restart is required. A Skill is executable only when its instructions explicitly reference a bundled script, and executable Skills require approval for their current content hash. Unreferenced validation or development scripts are shown as auxiliary scripts and are never executed by the writing workflow.

The Skill page reports conservative conflicts with project rules, including fragmented-prose directives, named-author imitation, and direct formal-manuscript writes. These warnings are advisory and never silently disable or rewrite a Skill.

## StoryState and safe revision

Each novel has an independent versioned StoryState. Models read the same authoritative facts and submit candidate output; only Runtime can promote a candidate to the formal manuscript. Cancelled runs, failed quality checks, invalid polish output, and stale tasks cannot overwrite the last committed manuscript.

The workbench exposes StoryState sections for manual correction. A save creates a normal `manual_edit` candidate and a new revision; stale edits and edits during an active run are rejected. Automatic post-write StoryState updates continue without per-chapter confirmation.

The old workbench **范文笔感** uploader is retired in favor of the learning library. Existing `style-samples/profile.json` data migrates lazily to a versioned prose baseline when the project learning view is first read; old files remain intact for rollback. After migration, the managed legacy block is excluded from runtime style context to avoid injecting the same rules twice. The workbench now shows a read-only summary and links to **学习库** for changes.

Run details include a context summary built from existing events and receipts: model route, Skills, prompt and constraint size, token usage, execution mode, tool receipts, and fallback state. Secrets and raw request headers are not exposed.

Short-story polish uses bounded segments with adjacent boundaries, a compact story map, character state, locked facts, and stage-specific Skills. Claude primary polish starts with an 8,192 output limit because the configured relay repeatedly exhausted smaller limits before returning visible prose. Other polish routes retain dynamic limits, so ordinary segments do not inherit Claude's cost profile. Final structured review also uses 8,192 to avoid truncated JSON.

## Reference learning library

The top-level **学习库** stores reference prose locally and separately from story projects. It accepts pasted text, UTF-8 TXT, DOCX, text-extractable PDF, and public HTTP/HTTPS pages, deduplicates identical content by SHA-256, and preserves immutable source versions. URL import rejects local/private destinations at every redirect. Scanned-PDF OCR is intentionally not included.

References are organized by platform, content type, and an optional related project. Import recommends these values locally from the title, URL, and opening text; users can override them before or after import. Unknown material falls back to `reference_work`, while `competitor_work` is manual-only. Search and platform/type/project filters operate together without changing the globally reusable source.

Content type controls purpose rather than project voice: `reference_work` yields narrative mechanisms, `platform_rule` supplements only same-platform final review, `popular_sample` enables a no-model report for title/first three lines/opening 500 characters/middle/turns/ending, `writing_tutorial` yields methods, and only `competitor_work` enters originality comparison. No classification automatically changes prose style or adopts a mechanism.

Local mechanisms now require a located trigger excerpt, structural position, transfer guidance, incompatible conditions, and confidence. Low-confidence proposals must be confirmed before project adoption. Repetition remains a review-only finding; loop/recurrence anchors with nearby state-change signals are labeled as possible intentional repetition instead of receiving an unconditional deletion instruction.

Rejected mechanisms disappear from the default candidate view immediately after rejection. The mechanism-status selector can show rejected items or all items for audit; rejected items remain read-only and cannot be confirmed, adopted, or rejected a second time.

Local extraction uses `learning-window-v2`: it scans the complete source in sentence/paragraph-safe 3,000-5,000 character windows, reports coverage, folds repeated mechanisms, and keeps every located evidence occurrence behind expandable details. Rejected mechanisms can be permanently deleted individually or in a batch only when no project has adopted them; adopted records and source TXT files are protected.

Reference metadata shows an explicit saved/dirty/saving/error state. A real change to platform, content type, or related project marks mechanisms already adopted from that source as requiring reconfirmation and marks the affected creative blueprint stale. Saving identical metadata is a no-op. Reconfirmation is explicit; metadata edits never rewrite formal prose.

**本地诊断** and **本地提炼** use deterministic Python rules only. **模型深度分析** uses the configured `reference_analysis` and `reference_synthesis` roles only after an explicit confirmation. Window and synthesis responses are schema-validated; malformed JSON structures use each role's configured fallback once, and a synthesis failure preserves completed window claims. A valid empty candidate list is shown as “未形成可逐条采纳的候选写法” instead of an ambiguous successful zero. Typed SQLite nodes, edges, evidence, and user revisions preserve provenance. Recommendations remain proposals until the user adopts them into one project.

Confirmed adoptions create versioned creative blueprints. Project learning also includes executable prose baselines, character voice profiles, epistemic boundaries, and scene briefs; active versions enter the existing planning/drafting/review/polish context, while stale versions are excluded. Character or world edits mark derived artifacts for review without rewriting an outline or manuscript.

Reference analysis also produces an evidence-backed narrative-attraction proposal. It separates opening pressure, anomalous action, surface and emotional goals, obstacle-effort-result cycles, accidents, evidence-supported reversals, question chains, relationship changes, and ending payoff/cost. Local extraction reports candidates rather than semantic certainty. After confirmation, only abstract transfer guidance enters the creative blueprint; source names, evidence excerpts, settings, and plot packaging remain outside generation context. Short projects turn that guidance into a target-length causal chain, where each cycle must change the available choices and repeated outcomes are reported before drafting.

**项目资料** and **学习库** render those same active or stale learning artifacts as readable Chinese sections, including versions and review status; they do not create another copy. Editing remains centralized in **学习库**. The new-book wizard lists every imported reference as a creation starting point. If a selected reference has not been locally distilled yet, the wizard performs that deterministic step first, then copies only the transferable mechanisms into editable premise and plot fields. The original “自己构思” path remains unchanged.

Candidate outlines use the existing planning route and are stored below `<project>/learning/candidates/`. Targeted `line_edit` uses its own role and stores candidate JSON below `<project>/learning/line-edits/`. Neither path overwrites formal files. Optional LTP neural NLP is installed, enabled, disabled, or uninstalled explicitly from **模型与 API**; it runs in a separate CPU process and fails open to deterministic rules.

The LTP installer pins compatible `transformers 4.x` and `huggingface-hub 0.x` dependencies. Its worker forces UTF-8 on Windows and uses `https://hf-mirror.com` for the first model download unless `HF_ENDPOINT` is already set. Cached analysis records `ltp-v2`; current and legacy LTP entity/SRL response shapes are both accepted. If the worker cannot load, the report explicitly marks LTP unavailable instead of presenting rule fallback as an LTP result.

Structural correction is scene-targeted. Every scene has a stable `scene-NN` id; a valid correction plan must include deterministic checks and may target at most 40% of scenes. Invalid or truncated plans stop the correction pass and preserve `best-candidate.md` instead of rewriting the whole manuscript. Exact consecutive duplicate paragraph blocks are removed locally before review.

Revision planning uses compact Skill/constraint prompts. If the planning role returns empty, truncated, or invalid JSON, the Runtime retries the plan once with the review role; a second invalid result fails closed and preserves the best candidate.

Polish input has circuit breakers: 120,000 tokens for the initial pass, 60,000 for each structural correction pass, and 220,000 across the run. Checkpoints are reused when resuming the same pass; failed editorial rounds are never reused as accepted corrections.

Ordinary prose polish uses bounded chunks and merges tiny trailing chunks when the merged request remains safe. Structural correction sends each targeted story scene once instead of repeating a scene-level task across subchunks. Its explicit length contract is 60%-180% of the source scene; ordinary polish remains 70%-160%. All instructions precede the manuscript marker so the model sees only source prose after `MANUSCRIPT SEGMENT`.

Only locally accepted candidates create checkpoints; rejected candidates remain retryable on resume.

For structural correction only, candidates in the 50%-60% compression gray zone may continue to final review when locked facts and local checks still pass. Runtime also re-aligns forbidden-text repair tasks to the scene that actually contains the exact text.

Operational details, log meanings, recovery behavior, and documentation requirements are in [`docs/maintenance.md`](docs/maintenance.md).

## Market trends and TXT ranking links

The **市场趋势** page provides local analysis of public ranking pages without calling a
model. The first adapter targets the Zhihu Salt Selection ranking page:

- **更新当前平台** creates a new immutable snapshot from a successful, non-empty parse.
- The Zhihu adapter reads the public ranking endpoint used by the page itself; the initial HTML
  contains loading skeletons rather than the completed ranking cards.
- The page shows category share, local heat and competition scores, ranking distribution,
  title/summary keywords, and the current work table.
- Trend claims require at least two valid snapshots. A 403, network failure, empty page, or
  incompatible page structure keeps the last successful data intact and shows the failure.
- Current, 7-day, 30-day, platform, ranking, and category filters only recompute local data.

The reference title can be left blank for a document import; the filename becomes the title.
After importing a TXT, use **查找榜单匹配** in its detail view. Matching normalizes the filename
and compares the opening text with the ranking summary. It only presents evidence and candidates:
the link is created after **确认关联**. Unlinking preserves the TXT, metadata, versions, and
project relationship.

Refreshing a ranking updates the market history attached to confirmed references. It does not
change reference text, user metadata, originality results, model analysis, final review, or
accepted/rejected decisions.

Confirmed ranking-linked references also form local cohort baselines by platform, ranking, category, and length. Fewer than five works are labelled insufficient, five to nine preliminary, and ten or more advisory. A wizard-selected baseline is saved as a versioned project learning artifact and enters planning and `manuscript-analysis-v2`; deviations are suggestions only and never block a coherent manuscript.

Short-story projects can enable **知乎盐选短篇创作配置** in the creation wizard or project settings. The profile keeps platform requirements separate from optional market advice and is reused by planning, drafting, revision, and final review. When no reliable cohort exists, the workflow continues with platform requirements only. Applying or changing the profile never edits the formal manuscript; it only changes later guidance and checks.

After a formal manuscript passes final review, the project can preview and create a versioned Zhihu submission package under `publication/zhihu/vNNN/`. The package contains the unchanged formal manuscript, user-confirmed submission metadata, the manuscript hash, and a compact copy of the existing review result. Missing fields, a changed manuscript, or a missing passed review produces a specific validation message. Export never calls a model and never overwrites an older package.

Ranking association is automatic only when there is one exact-title candidate and the imported opening also matches the ranking summary. Every other case stays unconfirmed for the user to decide. Market baselines keep the raw sample count and add an explainable local weight based on recency, observation days, best rank, and available interaction data.

Every reference import now returns and displays a plain-language receipt: the inferred or confirmed type, the evidence used, allowed uses, excluded uses, next actions, and whether a model was called. Import saves the source first; a failed or missing market match does not discard the reference. Long operations show explicit working, success, or failure states, and failed forms keep the entered values for retry.

The workbench **发布准备** section previews profile changes before applying them and states that manuscripts are not modified. For eligible Zhihu short projects it checks the formal manuscript and final-review result before showing a ready state, then keeps submission fields and specific retry guidance visible if export fails.

Candidate quality now includes a hash-bound narrative ledger for explicit questions, promises, setup/payoff candidates, and scene state changes. Important unresolved semantic candidates are included in the existing final-review evidence; no new model role is introduced. Revision issues use stable content-derived IDs, revision tasks can carry those IDs, and incremental final review must reconcile every prior issue as `resolved`, `unresolved`, or `uncertain`. Changed relation endpoints are reviewed together; broad, ambiguous, structural, or uncertain changes retain the full-manuscript fallback.

The feature only reads public ranking markup. It does not store credentials or cookies, read
member-only text, or bypass access controls. Its conclusions describe the captured platform
sample, not the whole fiction market. Future platforms use separate adapters and keep their raw
metrics; unlike units such as likes, readers, and monthly tickets are not directly compared.

## Long novels

Long setup may produce `memory/volumes.json` with machine-readable boundaries. When a generated chapter reaches `end_chapter`, the flywheel runs a volume audit and writes `memory/audits/volume-NN.json`.

A failed audit keeps the completed volume-ending chapter but blocks entry into the next volume. Resolve the audit findings and mark the audit passed before continuing.

Relevant chapter retrieval uses SQLite FTS and returns bounded matching prose excerpts rather than loading the whole novel into model context.

## Skill-driven project wizard

New projects use a resumable wizard. The wizard combines a stable core form with questions from `story-init`, `character-management`, `worldbuilding`, `plot-structure`, and compatible project-form sidecars under `forms/project.json`.

Unknown initialization Skills receive a validated generated form cached by Skill content hash under `data/skill-forms`. Updating a Skill selects a new cache entry automatically. Every answer is stored as one of:

- `locked`: program-enforced and included in every later model stage;
- `suggestible`: models may recommend changes;
- `generated`: the planning model may supply the value.

Before confirmation, **检查关键缺口** adds required follow-ups for missing endings, character arcs, world rules, and long-form main arcs. Confirmation creates the Story Skills schema-v2 project layout and saves locks in SQLite and `continuity/locks.json`.

## Controlled Skill Runtime

After project creation, the console runs the selected initialization Skills through a controlled runtime. External models may read story files, list entities, request missing input, and submit file or registry proposals. They cannot write directly.

Each Skill has a path allowlist. Proposed Markdown requires YAML frontmatter, locked facts are checked before acceptance, and conflicts create change requests. Accepted proposals are applied as one snapshot-protected transaction followed by Story CLI `reindex`, `links`, and `validate`.

The runtime exposes no general shell, arbitrary path, browser, MCP, or Codex tool access. Write-capable Skill execution requires native Tool Calling; prompt fallback is rejected rather than treated as successful execution.

## Existing project migration

The workbench can preview and run migration for an older project. Migration preserves legacy files, maps the old outline and canon into the canonical structure, sends ambiguous facts to `migration-report.json`, rebuilds registries, and restores the snapshot if Story CLI validation fails.
