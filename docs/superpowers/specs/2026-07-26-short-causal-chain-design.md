# Short Causal Chain Design

## Goal

Add a short-story whole-story causal chain that guides and checks the existing outline without replacing it. The chain follows the user's structure: goal, repeatable obstacle-effort-result cycles, accident, reversal, and ending.

## Scope

This feature applies to short stories first. It does not add per-chapter seven-step requirements, does not create a second story-state system, does not auto-adopt learning-library mechanisms, and does not overwrite confirmed outlines.

## Architecture

The existing outline remains the narrative source of truth. A new short_causal_chain project learning artifact stores a machine-readable causal index beside it. The artifact is included in project constraints, passed compactly to planning/draft/review/final-review prompts, and checked locally before model calls are trusted.

The learning library gains a causal-structure mechanism category. These patterns can be adopted into the existing creative_blueprint, but they stay abstract: no copied names, settings, plot packaging, or unique expressions.

## Data model

short_causal_chain contains core_goal, repeatable cycles, accidents, reversal, ending, status, and diagnostics. Cycles contain obstacle, effort, result, state_change, optional causes_next, and outline_refs.

The target cycle range is advisory: under 3,000 words uses 1-2 cycles; 3,000-8,000 uses 2-3; 8,000-15,000 uses 3-5; 15,000-30,000 uses 4-7; over 30,000 uses 5-9.

## Local checks

The local analyzer checks required nodes, cycle count, duplicate cycles, missing state changes, missing reversal evidence, and whether the ending answers the core goal. Ambiguous semantic matches are warnings, not blockers.

## Workflow integration

Planning receives instructions to append causal-chain JSON while preserving the normal outline. Runtime extracts the JSON if present, validates it, saves it as short_causal_chain, and continues with the original outline text. If extraction fails, the workflow continues and records a warning.

Draft receives a compact causal summary. It must follow the whole-story causal direction but may cover any amount of the chain per segment. Initial final review receives the compact chain and must check whether the finished manuscript fulfills it.

## Safety

Locked facts and user-confirmed project data outrank causal-chain suggestions. Learning-library mechanisms are abstract candidates only. Failed or invalid causal-chain extraction never blocks the old short-story workflow.
