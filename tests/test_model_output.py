import pytest

from novel_flywheel.model_output import parse_json_object


@pytest.mark.parametrize("text", [
    '{"result":"ok","nested":{"value":1}}',
    '```json\n{"result":"ok","nested":{"value":1}}\n```',
    '说明如下：\n<!-- result -->\n{"result":"ok","nested":{"value":1}}\n请查收。',
    '<!--\n{"result":"ok","nested":{"value":1}}\n-->',
    '\ufeff  {"result":"ok","nested":{"value":1}}  ',
])
def test_parse_json_object_accepts_one_payload_through_common_wrappers(text) -> None:
    assert parse_json_object(text) == {"result": "ok", "nested": {"value": 1}}


@pytest.mark.parametrize("text", [
    "没有 JSON",
    '{"truncated":',
])
def test_parse_json_object_rejects_missing_or_malformed_payload(text) -> None:
    with pytest.raises(ValueError, match="one valid JSON object"):
        parse_json_object(text)


def test_parse_json_object_rejects_wrong_top_level_type() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_json_object('[{"not":"an object payload"}]')


def test_parse_json_object_rejects_multiple_valid_payloads() -> None:
    text = '示例：{"result":"example"}\n最终：{"result":"real"}'

    with pytest.raises(ValueError, match="multiple JSON objects"):
        parse_json_object(text)


def test_parse_json_object_does_not_salvage_nested_object_from_broken_envelope() -> None:
    with pytest.raises(ValueError, match="one valid JSON object"):
        parse_json_object('{"result":{"looks":"valid"},"unfinished":')


def test_parse_json_object_ignores_json_inside_ordinary_html_comment() -> None:
    text = '<!-- example: {"result":"wrong"} -->\n{"result":"real"}'

    assert parse_json_object(text) == {"result": "real"}


def test_parse_json_object_preserves_html_comment_text_inside_json_string() -> None:
    text = '{"message":"keep <!-- literal --> intact"}'

    assert parse_json_object(text) == {"message": "keep <!-- literal --> intact"}


def test_parse_json_object_rejects_multiple_html_comment_envelopes() -> None:
    with pytest.raises(ValueError):
        parse_json_object('<!-- {"result":"one"} -->\n<!-- {"result":"two"} -->')


def test_parse_json_object_normalizes_full_width_syntax_not_string_content() -> None:
    text = '｛＂result＂：＂ok＂，＂count＂：１２，＂literal＂：＂保留１２：｛原文｝＂｝'

    assert parse_json_object(text) == {
        "result": "ok", "count": 12, "literal": "保留１２：｛原文｝",
    }


def test_parse_json_object_rejects_valid_example_followed_by_truncated_result() -> None:
    text = '示例：{"result":"example"}\n最终：{"result":'

    with pytest.raises(ValueError, match="additional malformed JSON value"):
        parse_json_object(text)
