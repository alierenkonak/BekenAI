from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from beken_retrieval.model_catalog import ModelCatalog


@dataclass(frozen=True)
class RetrievalProfile:
    domain: str
    version: str
    scope_version: str
    lexical_backend: str
    dense_model: str
    fusion: str
    fusion_k: int
    reranker_model: str
    hybrid_candidate_limit: int
    result_limit: int
    selection_status: str
    quality_gate_status: str
    channel_scopes: dict[str, str] = field(default_factory=dict)
    # How new BM25 indexes stem words (see tokenization.prefix_stem); an index records its
    # own method, so changing this affects only indexes built afterwards.
    lexical_stemming: str | None = None

    def scope_for_channel(self, channel: str) -> str:
        if channel == "primary":
            return self.channel_scopes.get("primary", self.scope_version)
        try:
            return self.channel_scopes[channel]
        except KeyError as exc:
            raise ValueError(
                f"No retrieval scope configured for {self.domain}/{channel}"
            ) from exc

    def validate_selection(
        self,
        *,
        dense_model: str,
        reranker_model: str,
        candidate_limit: int,
    ) -> None:
        expected = {
            "dense model": (dense_model, self.dense_model),
            "reranker": (reranker_model, self.reranker_model),
            "candidate limit": (candidate_limit, self.hybrid_candidate_limit),
        }
        mismatches = [
            label for label, (actual, configured) in expected.items() if actual != configured
        ]
        if mismatches:
            raise ValueError(
                f"Selection does not match retrieval profile for {self.domain}: "
                + ", ".join(mismatches)
            )

    def validate_active_manifest(self, payload: dict) -> None:
        dense = payload.get("dense") or {}
        channel = str(payload.get("channel") or "primary")
        if payload.get("domain") != self.domain:
            raise ValueError(f"Active index domain does not match profile for {self.domain}")
        manifest_scope = payload.get("scope_version")
        if manifest_scope is None and channel == "primary":
            manifest_scope = self.scope_version
        if manifest_scope != self.scope_for_channel(channel):
            raise ValueError(
                f"Active index scope does not match profile for {self.domain}/{channel}"
            )
        self.validate_selection(
            dense_model=str(dense.get("model_key") or ""),
            reranker_model=str(payload.get("reranker_model_key") or ""),
            candidate_limit=int(payload.get("hybrid_candidate_limit") or 0),
        )


class RetrievalProfileCatalog:
    def __init__(self, profiles: dict[str, RetrievalProfile]) -> None:
        self.profiles = profiles

    @classmethod
    def load(cls, path: Path, *, models: ModelCatalog) -> RetrievalProfileCatalog:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profiles: dict[str, RetrievalProfile] = {}
        for domain, values in payload.items():
            profile = RetrievalProfile(domain=domain, **values)
            if profile.lexical_backend != "bm25s":
                raise ValueError(f"Unsupported lexical backend: {profile.lexical_backend}")
            if profile.fusion != "rrf" or profile.fusion_k <= 0:
                raise ValueError("Retrieval profile must use RRF with a positive k")
            if profile.hybrid_candidate_limit < profile.result_limit:
                raise ValueError("Candidate limit cannot be smaller than result limit")
            models.get(profile.dense_model)
            models.get(profile.reranker_model)
            profiles[domain] = profile
        return cls(profiles)

    def get(self, domain: str) -> RetrievalProfile:
        try:
            return self.profiles[domain]
        except KeyError as exc:
            raise ValueError(f"No retrieval profile configured for domain: {domain}") from exc
