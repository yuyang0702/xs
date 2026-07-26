from novel_flywheel.popular_analysis import analyze_popular_sample


def test_popular_report_covers_reader_retention_arc_with_evidence() -> None:
    text = (
        "我死后的第三天，凶手参加了我的葬礼。\n"
        "他为什么敢来？\n"
        "我决定跟上他。\n\n"
        + "我发现一条新线索，随后改变了计划。" * 80
        + "\n\n原来他不是凶手，真正的危险刚刚出现。"
    )
    report = analyze_popular_sample("我死后凶手来参加葬礼", text)
    assert set(report["sections"]) == {
        "title", "first_three_lines", "opening_500",
        "middle", "turning_points", "ending",
    }
    assert report["model_calls"] == 0
    assert report["sections"]["opening_500"]["evidence"]
    assert all(
        {"start", "end", "excerpt"} <= item.keys()
        for item in report["sections"]["opening_500"]["evidence"]
    )
