from assistant.backend.main import summarize_history_result


def test_history_summary_keeps_ranked_deidentified_candidates():
    result = summarize_history_result(
        "spreadsheet_query",
        {
            "rows": [{"label": "erp-a"}],
            "facets": {
                "stations": [
                    {"label": "erp-a", "province": "广东省区", "value": 8},
                    {"label": "erp-b", "province": "广东省区", "value": 6},
                ],
                "issue_types": [],
            },
        },
    )

    assert result["candidates"] == [
        {"rank": 1, "type": "station", "label": "erp-a", "province": "广东省区", "value": 8},
        {"rank": 2, "type": "station", "label": "erp-b", "province": "广东省区", "value": 6},
    ]


def test_history_summary_does_not_retain_rows():
    result = summarize_history_result(
        "spreadsheet_query",
        {"rows": [{"customer": "sensitive-row"}], "facets": {"stations": [], "issue_types": []}},
    )

    assert "sensitive-row" not in str(result)
