STAGE_SYSTEM = {
    "planning": (
        "Design a complete causal story plan. Preserve the requested ending and hard constraints. "
        "Use all supplied project facts, include the requested segment map, and never ask the user questions."
    ),
    "revision_plan": (
        "Act as a structural revision editor. Convert the supplied chief-editor findings into the "
        "smallest actionable cross-segment correction plan. Preserve locked facts and return only "
        "the requested strict JSON object."
    ),
    "draft": (
        "Write publishable fiction prose from the approved plan. Prioritize scenes, causality, and voice. "
        "Never ask the user for information; infer minor details without changing locked facts."
    ),
    "review": (
        "Act as a commercial fiction editor. Audit paid-reading motivation, hook and payoff density, "
        "causality, emotion, character knowledge, OOC, continuity, prose, and compliance. Return only "
        "strict JSON with dimensions commercial/story/prose (0-100), hard_fail, decision "
        "pass/revise/rewrite, and issues containing category, severity, evidence, and action. "
        "Compliance or canon violations set hard_fail=true; compliance never increases quality scores."
    ),
    "polish": "Revise only from the supplied draft and findings. Preserve plot facts while removing AI-like prose.",
    "final_review": (
        "Act as the independent chief editor. Audit the revised manuscript without rewriting it. "
        "Return only strict JSON with dimensions commercial/story/prose (0-100), hard_fail, decision "
        "pass/revise/rewrite, and issues containing category, severity, evidence, and action. "
        "Measure actual reading quality, emotional payoff, and paid-reading pull. Compliance or canon "
        "violations set hard_fail=true and never add quality points."
    ),
    "maintenance": "Extract durable canonical facts from the final text. Return strict JSON with a facts array.",
}

REQUIRED_SKILLS = {
    "planning": ["story-init", "plot-structure", "character-management", "worldbuilding"],
    "revision_plan": ["revision-continuity", "plot-structure"],
    "draft": ["chapter-writing", "novel-writing", "dialogue"],
    "review": ["revision-continuity"],
    "polish": ["humanizer-zh", "dialogue", "novel-writing"],
    "final_review": ["revision-continuity"],
    "maintenance": ["story-maintenance"],
}
