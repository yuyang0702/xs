from novel_flywheel.reference_classification import classify_reference


def test_classifies_platform_rules_and_platform_without_a_model() -> None:
    result = classify_reference(
        "知乎投稿规范",
        "投稿要求：正文不得少于三千字，禁止抄袭，必须使用中文。",
        "https://www.zhihu.com/question/1",
    )
    assert result["content_type"] == "platform_rule"
    assert result["platform"] == "知乎"
    assert result["confidence"] >= 0.8


def test_classifies_tutorial_popular_and_default_reference() -> None:
    assert classify_reference("小说写作教程", "本文讲解开头写作技巧和案例分析。")["content_type"] == "writing_tutorial"
    assert classify_reference("知乎高赞爆款", "热门回答，阅读量十万。")["content_type"] == "popular_sample"
    assert classify_reference("雪夜", "她推开门，看见院子里站着一个陌生人。")["content_type"] == "reference_work"


def test_classifier_never_automatically_selects_competitor() -> None:
    assert classify_reference("竞品小说", "这是同题材竞争作品。")["content_type"] != "competitor_work"
