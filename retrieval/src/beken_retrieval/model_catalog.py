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
        return cls({key: ModelSpec(key=key, **value) for key, value in payload.items()})

    def get(self, key: str) -> ModelSpec:
        try:
            return self.specs[key]
        except KeyError as exc:
            raise ValueError(f"Unknown pinned model: {key}") from exc
