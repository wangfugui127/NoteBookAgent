from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.service import should_expand_graph
from app.retrieval.types import SearchHit


def hit(chunk_id: str, score: float = 1.0) -> SearchHit:
    return SearchHit(chunk_id, chunk_id, score, "doc", "version", "title")


def test_rrf_deduplicates_and_tracks_sources() -> None:
    results = reciprocal_rank_fusion(
        [("dense", [hit("a"), hit("b")]), ("graph", [hit("b"), hit("c")])]
    )
    assert [item.chunk_id for item in results][0] == "b"
    assert results[0].sources == ["dense", "graph"]


def test_graph_auto_routing_is_deterministic() -> None:
    assert should_expand_graph("比较 BERT 和 RAG 使用的数据集关系")
    assert not should_expand_graph("帮我总结这一段")
