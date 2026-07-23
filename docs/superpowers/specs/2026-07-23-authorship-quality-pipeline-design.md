# Authorship Quality Pipeline Design

## Goal

Reduce formulaic AI-like fiction without repeatedly rewriting whole manuscripts, preserve the best candidate, and let the user explicitly publish a reviewed candidate.

## Boundaries

- AI-likeness is a soft editorial signal, never a hard failure by itself.
- Compliance, corrupted manuscript content, severe canon conflicts, and missing required story material remain hard failures.
- Diagnostics and validation are local and deterministic. They do not call paid models.
- Model revision is segment-targeted. Unaffected segments remain byte-for-byte unchanged.

## Project Style Context

Each project has `style-profile.md`. It records narrative viewpoint, distance, sentence rhythm, description density, emotional expression, ending behavior, preferred expressions, and forbidden expressions. New projects receive a deterministic profile derived from their metadata. Existing projects receive it lazily when a workflow starts.

Character files remain the source of character voice. A compact voice fingerprint is extracted from fields and prose such as speech habits, forms of address, sentence style, emotional behavior, and forbidden vocabulary. Polish prompts receive only fingerprints for characters named in the target segment.

## Local Prose Diagnostics

A focused analyzer reports findings with code, severity, segment, excerpt, and count. It detects production/editorial text, formulaic transitions, explanatory emotion, theme-summary endings, repetitive sentence openings, uniform short-sentence runs, repeated sensory motifs, and repeated weak adverbs. Production text is blocking because it corrupts the manuscript. Other findings are soft.

The report includes a 0-100 naturalness score for display and comparison. It is not presented as an AI detector and is not added to the commercial/story/prose quality gate.

## Targeted Polish And Validation

Diagnostics select only affected segments for polish. The model receives the style profile, relevant character fingerprints, local findings, the source segment, and small adjacent context. Every candidate segment is checked locally before acceptance:

- no production text;
- length ratio remains within 0.70-1.60;
- locked names and required literal facts from the source remain present;
- deterministic revision checks pass;
- soft diagnostic count does not materially regress.

Rejected segments retain their source text. Mechanical typography normalization runs after every polish, not only structural correction runs.

## Review Policy

Review issues are normalized into `blocking`, `targeted_revision`, or `advisory`. Only explicit blocking categories can keep `hard_fail`: compliance, canon corruption, manuscript corruption, missing required content, and production text. Style, prose, pacing, dialogue, commercial pull, historical realism, and ending quality are targeted or advisory unless they describe an explicit blocking condition.

The final review prompt contains these rules. Runtime normalization remains authoritative if a model over-classifies a soft issue as critical.

## Candidate Publication

The console displays the latest best candidate and its diagnostic summary. A user can select “设为正式成品”. The backend resolves the candidate from project-owned run artifacts, normalizes typography, rejects production text or an empty/truncated manuscript, writes the formal manuscript atomically, and records publication metadata. No arbitrary browser path is accepted.

Short projects publish to `manuscript/story.md` and `chapters/chapter-01.md`. Long projects can publish a candidate only when it represents one chapter and has an explicit chapter target; otherwise publication is rejected to avoid overwriting a multi-chapter project incorrectly.

## Long-Fiction Monitoring

After each completed long chapter, local metrics are stored beside the chapter: sentence-length distribution, dialogue ratio, description proxy, repeated openings, weak-adverb density, and character voice markers. The current chapter is compared with up to five preceding chapters. Material drift becomes an advisory diagnostic and can target a later local polish; it never blocks archiving by itself.

Historical and procedural realism remain explicit review categories. They produce targeted revision findings, not hard failures, unless they contradict a locked year, setting, or canonical fact.

## UI And Logging

The workbench shows naturalness score, blocking count, targeted finding count, and the most important excerpts. Publication requires a confirmation dialog and refreshes file locations immediately. Workflow logs report diagnostic start, targeted segments, accepted/rejected segment changes, typography repair, drift results, and publication.

## Testing

Unit tests cover diagnostics, issue classification, segment validation, profile generation, and drift comparison. API tests cover candidate inspection and controlled publication. Workflow tests verify unaffected segments remain unchanged and mechanical repair always runs. Console tests verify the diagnostic and publication controls exist.
