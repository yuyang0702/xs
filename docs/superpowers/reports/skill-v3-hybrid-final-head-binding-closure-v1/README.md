# Skill V3 Hybrid final-HEAD binding closure

This directory seals the offline source, test, and pre-authorization evidence
for generating the executable campaign authorization only after the repository
has reached its final clean HEAD. The executable UTF-8 authorization and its
hash-only receipt are deliberately created outside the Git worktree after the
commit containing this directory. No authorization bytes in this directory
authorize execution.
