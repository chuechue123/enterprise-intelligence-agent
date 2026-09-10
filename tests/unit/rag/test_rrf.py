from bizinsight.rag.hybrid import reciprocal_rank_fusion


def test_rrf_promotes_shared_high_rank_result() -> None:
    result = reciprocal_rank_fusion([["a", "shared"], ["shared", "b"]])
    assert result[0] == "shared"
