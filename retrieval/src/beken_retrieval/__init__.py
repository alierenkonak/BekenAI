"""Domain-aware lexical, semantic, and hybrid legal retrieval."""

from beken_retrieval.coordinator import DomainSearchCoordinator, SearchMode
from beken_retrieval.models import ChunkRecord, SearchFilters, SearchHit

__all__ = [
    "ChunkRecord",
    "DomainSearchCoordinator",
    "SearchFilters",
    "SearchHit",
    "SearchMode",
]
