# Slice1 Phase B CURRENT-Skill single-use approval

This directory seals the user's fresh, single-use approval for the already
materialized CURRENT-Skill Phase B baseline. It does not execute or reserve the
run. The sealed materialization files in the parent directory remain unchanged.

The approval expires at `2026-08-25T03:29:00Z`. A separate execute-once task
must revalidate the complete approval manifest and signed launch gate before
credential lookup, then atomically reserve the nonce.
