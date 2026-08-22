# Repo-owned novel Skill source bundle

This directory preserves the complete source assets of the eleven novel Skills
used or audited at the sealed parent baseline. It is an inactive source bundle:
the production `SkillScanner`, `SkillGate`, stage registry, prompts, and runtime
do not scan or load this directory.

- Bundle identity: `REPO_OWNED_INACTIVE_V1`
- Source kind: `user_global_codex_skill`
- Source root: `source/<skill-id>/`
- Runtime reachability: `NONE`
- Content policy: byte-preserving copy; no Skill text or executable is edited
- EOL policy: repository checkout uses LF under this bundle root
- Executable policy: `story-maintenance` is preserved for a future
  approval-bound executable-only role and is not executed by this bundle

The content-addressed lock, full file inventory, dependency closure, copy parity,
privacy scan, EOL provenance, runtime non-reachability proof, and dispositions are
sealed under `docs/superpowers/reports/project-skill-portable-bundle/`.

Restoring these files on another computer does not by itself install required
runtime executables. In particular, the executable-only maintenance package
requires a compatible Node.js runtime. The source bundle must not be copied into
`.agents/skills/` or added to a production scanner root without a separate design,
approval, and parity migration.
