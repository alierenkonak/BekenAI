from __future__ import annotations

from collections.abc import Sequence

from beken_retrieval.models import SearchHit


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[SearchHit]],
    *,
    limit: int,
    k: int = 60,
    score_key: str = "rrf",
) -> list[SearchHit]:
    fused: dict[str, float] = {}
    records: dict[str, SearchHit] = {}
    breakdowns: dict[str, dict[str, float]] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            chunk_id = hit.record.chunk_id
            contribution = 1.0 / (k + rank)
            fused[chunk_id] = fused.get(chunk_id, 0.0) + contribution
            records.setdefault(chunk_id, hit)
            breakdown = breakdowns.setdefault(chunk_id, {})
            for key, value in hit.score_breakdown.items():
                breakdown[key] = value
            breakdown[score_key] = fused[chunk_id]

    ordered = sorted(fused, key=lambda chunk_id: (-fused[chunk_id], chunk_id))[:limit]
    return [
        SearchHit(
            record=records[chunk_id].record,
            score=fused[chunk_id],
            rank=rank,
            score_breakdown=breakdowns[chunk_id],
        )
        for rank, chunk_id in enumerate(ordered, start=1)
    ]
