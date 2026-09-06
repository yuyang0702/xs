# Anthropic semantic completion and successor evidence

The semantic message becomes complete only after the existing state validator accepts `message_stop`. The iterator continues to EOF. A later `ping` is a non-semantic keepalive and increments `POST_TERMINAL_PING_COUNT` and `POST_TERMINAL_PING_IGNORED_COUNT`; it cannot modify text, tools, identity, stop reason or usage. A later error retains the typed Provider error. Any other later event, including a duplicate stop, remains invalid.

Official documentation allows any number of pings throughout a response. Official low-level SDK iteration ignores ping and retains error handling after yielding message_stop. Post-stop acceptance is a compatibility inference from that behavior, not an explicit documented post-stop allowance. Unknown event strictness remains this project's bounded policy.

Capture terminal detection may recognize a delimiter-complete suffix of message_stop followed only by pings. This detector is a byte-completeness hint; the response adapter remains the semantic authority for local replay. Other protocol terminals gain no trailing-ping exception. Usage extraction independently rejects Provider errors and semantic events after the first stop, and ignores all ping extensions. A usage receipt alone is never Message or workload acceptance.

The successor keeps eight capacity obligations, while dispatching only the explicitly selected six or seven remaining cases. Historical accepted probe 01 and a replay-proven probe 02 retain their original authorization, head, nonce, exact request, capture and acceptance provenance. A new versioned admission may authorize their bounded capacity evidence; it must never present them as fresh dispatches or add their usage to successor request counters. Actual usage and estimator-derived budget reserves remain separate.

All source and preparation proof changes precede the frozen execution HEAD. The fresh external authorization binds this Master, protocol evidence, exact replay, request zero-diff, response matrix, selected cases, historical admission, current routes and all Runtime gates. Legacy authorizations and terminal journals remain immutable. An actual dispatched successor failure seals STOP; a second Full Short and whole-run retry remain forbidden.

No database migration is required for the response policy. Legacy external schemas remain unchanged; the new successor schema is opt-in and rejects incomplete or mismatched lineage. Repeated validation must be idempotent and must not reserve nonces or create dispatch authority.
