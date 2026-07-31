# Outline Canon and Segment Gates

## Goal

Prevent a confirmed outline, planning response, or draft segment from mixing project identities, repeating another segment's event, or reaching publication with mechanical manuscript corruption. Preserve the existing StoryState authority, model roles, candidate review, fallbacks, and formal manuscript protections.

## Decisions

- `StoryState.confirmed_facts` remains the authority for user-approved outline overrides. No schema or second state store is added.
- Candidate comparison shows the project value, candidate value, and final choice. Locked project requirements cannot be overridden from the outline screen.
- A conflicting candidate can seed a separate project. The source project remains unchanged; the new project uses the existing initialization workflow to regenerate materials.
- A short plan contains one numbered block per segment. Each block owns its events exclusively and records its opening and closing character location, action, relationship, and knowledge state.
- A draft segment sees its own block, whole-story segment titles, the previous block's exact closing handoff, and the previous prose tail. It explicitly bridges a time or location change.
- Planning and segment gates allow one model correction. Persistent failure stops before later stages and preserves completed artifacts.
- Canonical full-text analysis runs at draft, polish, and pre-publication boundaries. Only deterministic mechanical repairs occur without user confirmation.
- Existing planning, draft, review, polish, final-review, and maintenance role bindings and configured fallbacks remain unchanged.

## Acceptance criteria

1. A candidate that changes the established protagonist or primary location cannot be applied without a visible choice.
2. Keeping the project fact yields a conflict-free formal outline; adopting an unlocked value records a confirmed fact.
3. The same conflicting candidate can create an independent project without changing the source project.
4. A short plan without exactly one event block per segment cannot enter drafting.
5. Each segment prompt contains only its owned plan block plus bounded handoff context.
6. Unbridged location changes, repeated paragraphs, production notes, mixed-script corruption, and severe length drift fail the segment gate.
7. A publish candidate with a local blocking prose finding cannot replace the formal manuscript.
8. The quality page defaults to three issues and identifies the source and responsible handler in plain Chinese.

## Rollback

The change is code-only and adds no migration. Rolling back restores the former comparison and drafting behavior. Existing StoryState revisions, candidates, projects, manuscripts, run history, and model bindings remain readable.
