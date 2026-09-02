from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model_id: str
    revision: str
    backend: str
    safe_artifact: str
    supporting_artifacts: tuple[str, ...] = ()
    dimensions: int | None = None
    max_tokens: int | None = None
    query_prefix: str = ""
    passage_prefix: str = ""


class ModelCatalog:
    def __init__(self, specs: dict[str, ModelSpec]) -> None:
        self.specs = specs

    @classmethod
    def load(cls, path: Path) -> ModelCatalog:
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs = {}
        for key, value in payload.items():
            normalized = dict(value)
            normalized["supporting_artifacts"] = tuple(
                normalized.get("supporting_artifacts", ())
            )
            specs[key] = ModelSpec(key=key, **normalized)
        return cls(specs)

    def get(self, key: str) -> ModelSpec:
        try:
            return self.specs[key]
        except KeyError as exc:
            raise ValueError(f"Unknown pinned model: {key}") from exc
