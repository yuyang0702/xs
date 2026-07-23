# Compact Skill Prompts Design

## Goal

Reduce external polish-model request size without changing Skill discovery, approval, executable Skill behavior, or source files.

## Design

Only the `polish` model stage receives compact prompt text. A deterministic compactor removes frontmatter, usage instructions, references, and long examples while retaining headings plus normative rules such as must, never, preserve, avoid, and numbered or bulleted execution guidance. Other stages continue receiving complete Skill prompts.

The compact prompt is cached by the ordered Skill content hashes. A changed Skill therefore produces a new cache entry automatically. If compaction raises an error, produces no useful rules, or cannot reduce the prompt safely, the existing full prompt is used.

The runtime still records the original Skill names and hashes. No Skill file is rewritten, and executable Skills remain unchanged.

## Acceptance

- Hard-rule sections and normative lines survive compaction.
- Examples, trigger metadata, and reference-loading instructions are omitted.
- Only `polish` uses compact prompts.
- Cache keys change when Skill content changes.
- Any compaction failure falls back to the complete prompt.
- Existing workflows and tests continue to pass.
