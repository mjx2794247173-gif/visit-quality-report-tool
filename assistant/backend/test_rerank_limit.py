from assistant.backend.main import MAX_FINAL_RERANK_SOURCES, RetrievalRanking, filter_ranked_sources


def test_rerank_keeps_at_most_three_relevant_sources():
    sources = [{"source": f"s{i}", "text": f"text-{i}"} for i in range(6)]
    ranking = RetrievalRanking(
        ranked_indices=[0, 1, 2, 3, 4, 5],
        relevant_indices=[0, 1, 2],
    )

    result = filter_ranked_sources(sources, ranking)

    assert MAX_FINAL_RERANK_SOURCES == 3
    assert len(result) == 3
    assert [item["source"] for item in result] == ["s0", "s1", "s2"]


def test_rerank_schema_rejects_more_than_three_relevant_sources():
    try:
        RetrievalRanking(
            ranked_indices=[0, 1, 2, 3],
            relevant_indices=[0, 1, 2, 3],
        )
    except Exception:
        return
    raise AssertionError("relevant_indices must be capped at three")
