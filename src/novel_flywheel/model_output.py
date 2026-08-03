from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any


_JSON_TOKEN_CHARACTERS = frozenset('{}[]:,.+-0123456789truefalsnulEe \t\r\n')


def normalize_model_label(value: object) -> str:
    """Normalize a generated control label without touching free-form prose."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[\s\-]+", "_", text)


def canonical_model_label(
    value: object, aliases: Mapping[str, str],
) -> str | None:
    """Return a documented control value or None for an unknown description."""
    return aliases.get(normalize_model_label(value))


def _normalize_json_syntax(text: str) -> str:
    """Normalize full-width JSON syntax without changing JSON string content."""
    result: list[str] = []
    quote = ""
    escaped = False
    for character in text:
        if quote:
            if escaped:
                escaped = False
                result.append(character)
            elif character == "\\":
                escaped = True
                result.append(character)
            elif character == quote:
                quote = ""
                result.append('"')
            else:
                result.append(character)
            continue
        if character in {'"', '＂'}:
            quote = character
            result.append('"')
            continue
        if character == "\u3000" or unicodedata.east_asian_width(character) == "F":
            normalized = unicodedata.normalize("NFKC", character)
            if len(normalized) == 1 and normalized in _JSON_TOKEN_CHARACTERS:
                character = normalized
        result.append(character)
    return "".join(result)


def parse_json_object(text: str, *, label: str = "Model output") -> dict[str, Any]:
    """Read one JSON object through harmless wrappers and reject ambiguity."""
    source = str(text or "").lstrip("\ufeff").strip()
    try:
        direct = json.loads(source)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(direct, dict):
            return direct
        raise ValueError(f"{label} must be a JSON object")

    # A full HTML comment may intentionally be the payload envelope. Do this
    # only after trying the original JSON so comment-like prose inside a JSON
    # string is never rewritten.
    first_comment_end = source.find("-->", 4) if source.startswith("<!--") else -1
    if source.startswith("<!--") and first_comment_end == len(source) - 3:
        source = source[4:-3].strip()
        try:
            direct = json.loads(source)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(direct, dict):
                return direct
            raise ValueError(f"{label} must be a JSON object")

    source = _normalize_json_syntax(source)
    try:
        direct = json.loads(source)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(direct, dict):
            return direct
        raise ValueError(f"{label} must be a JSON object")

    candidates: list[Any] = []
    stack: list[str] = []
    start = -1
    in_string = False
    escaped = False
    malformed_container = False
    index = 0
    while index < len(source):
        # Ordinary HTML comments are presentation wrappers only when they are
        # outside a JSON container. Skip them without mutating any candidate.
        if not stack and source.startswith("<!--", index):
            comment_end = source.find("-->", index + 4)
            if comment_end < 0:
                break
            index = comment_end + 3
            continue

        character = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if stack and character == '"':
            in_string = True
            index += 1
            continue
        if character in "{[":
            if not stack:
                start = index
            stack.append(character)
            index += 1
            continue
        if character not in "}]" or not stack:
            index += 1
            continue
        expected = "{" if character == "}" else "["
        if stack[-1] != expected:
            malformed_container = malformed_container or (
                start >= 0 and source[start:start + 1] == "{"
            )
            stack.clear()
            start = -1
            index += 1
            continue
        stack.pop()
        if stack or start < 0:
            index += 1
            continue
        try:
            candidates.append(json.loads(source[start:index + 1]))
        except json.JSONDecodeError:
            malformed_container = malformed_container or source[start] == "{"
        start = -1
        index += 1

    malformed_container = malformed_container or bool(
        stack and start >= 0 and source[start:start + 1] == "{"
    )

    objects = [value for value in candidates if isinstance(value, dict)]
    if len(objects) == 1:
        if malformed_container:
            raise json.JSONDecodeError(
                f"{label} contains an additional malformed JSON value", source, 0,
            )
        return objects[0]
    if len(objects) > 1:
        raise ValueError(f"{label} contains multiple JSON objects")
    if candidates:
        raise ValueError(f"{label} must be a JSON object")
    raise json.JSONDecodeError(
        f"{label} does not contain one valid JSON object", source, 0,
    )
