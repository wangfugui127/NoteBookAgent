from collections import defaultdict

from app.retrieval.types import SearchHit


def reciprocal_rank_fusion(
    result_sets: list[tuple[str, list[SearchHit]]], k: int = 60, limit: int = 20
) -> list[SearchHit]:
    scores: dict[str, float] = defaultdict(float)
    hits: dict[str, SearchHit] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    for source_name, result_set in result_sets:
        for rank, hit in enumerate(result_set, start=1):
            scores[hit.chunk_id] += 1.0 / (k + rank)
            hits[hit.chunk_id] = hit
            sources[hit.chunk_id].add(source_name)
    ordered = sorted(scores, key=scores.get, reverse=True)[:limit]  # type: ignore[arg-type]
    output: list[SearchHit] = []
    for chunk_id in ordered:
        hit = hits[chunk_id]
        hit.score = scores[chunk_id]
        hit.sources = sorted(sources[chunk_id])
        output.append(hit)
    return output
