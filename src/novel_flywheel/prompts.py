STAGE_SYSTEM = {
    "planning": "Design a complete causal story plan. Preserve the requested ending and hard constraints.",
    "draft": "Write the complete fiction draft from the approved plan. Prioritize scenes, causality, and voice.",
    "review": "Audit compliance, causality, character knowledge, OOC, pacing, and length. Return strict JSON.",
    "polish": "Revise only from the supplied draft and findings. Preserve plot facts while removing AI-like prose.",
    "final_review": "Independently audit the revised manuscript. Return strict JSON and do not rewrite prose.",
    "maintenance": "Extract durable canonical facts from the final text. Return strict JSON with a facts array.",
}

REQUIRED_SKILLS = {
    "planning": ["story-init", "plot-structure", "character-management", "worldbuilding"],
    "draft": ["chapter-writing", "novel-writing", "dialogue"],
    "review": ["revision-continuity"],
    "polish": ["humanizer-zh", "dialogue", "novel-writing"],
    "final_review": ["revision-continuity"],
    "maintenance": ["story-maintenance"],
}
