# Targeted Structural Revision Design

## Problem

The current correction loop sends the same truncated review to every manuscript segment. Each model sees only the current segment and the previous tail, so global continuity, causality, and ending problems cannot converge reliably.

## Design

Before each structural correction, the existing planning role receives the complete normalized findings and a compact map of every manuscript segment. It returns JSON containing global facts, explicit checks, and revision tasks mapped to segment numbers. Runtime validates the plan and falls back to conservative all-segment revision if the plan is malformed.

Only affected segments are revised. Each call receives its task list, the global facts and checks, the compact story map, the previous revised tail, and the next original head. Unaffected segments remain byte-for-byte unchanged. Structural output length protection remains active, with a wider lower bound only when the plan explicitly permits removal.

After assembly, Runtime applies deterministic text checks from the validated plan. A failed check is recorded and passed to the chief editor; it does not silently publish the manuscript. Existing best-score rollback remains responsible for preventing a lower-scoring revision from replacing the best candidate.

## Observability

Run events record revision-plan creation or fallback, targeted segment IDs, unchanged segments, rejected segment output, and deterministic check failures. The plan is written to the run outputs for diagnosis.

## Token Control

The planner receives a compact segment map rather than the full manuscript. Only affected segments are sent to the polish model. Findings are structurally compacted instead of cut at an arbitrary character boundary.

