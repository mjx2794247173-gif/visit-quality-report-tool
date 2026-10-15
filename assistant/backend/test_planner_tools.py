from assistant.backend.main import PLANNER_TOOLS


def test_planner_exposes_distinct_safe_capabilities():
    names = {item["function"]["name"] for item in PLANNER_TOOLS}
    assert names == {
        "spreadsheet_query",
        "knowledge_retrieval",
        "data_quality_check",
        "feishu_publish_preview",
    }


def test_planner_tool_schemas_reject_extra_arguments():
    assert all(
        item["function"]["parameters"].get("additionalProperties") is False
        for item in PLANNER_TOOLS
    )


def test_feishu_function_only_prepares_a_confirmed_preview():
    tool = next(
        item["function"]
        for item in PLANNER_TOOLS
        if item["function"]["name"] == "feishu_publish_preview"
    )
    assert "只准备内容" in tool["description"]
    assert tool["parameters"]["properties"] == {}
