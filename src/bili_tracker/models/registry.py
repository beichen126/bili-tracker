from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import urlparse

from bili_tracker.domain.errors import ManifestError
from bili_tracker.domain.models import ModelAsset


class ModelRegistry:
    def __init__(self, assets: dict[str, ModelAsset]) -> None:
        self._assets = dict(assets)

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        allowed_domains: set[str] | None = None,
    ) -> ModelRegistry:
        domains = allowed_domains or {"openaipublic.azureedge.net", "huggingface.co"}
        assets: dict[str, ModelAsset] = {}
        for path in sorted(directory.glob("*.toml")):
            with path.open("rb") as handle:
                values = tomllib.load(handle)
            asset = ModelAsset.from_mapping(values)
            for source in asset.sources:
                if urlparse(source).hostname not in domains:
                    raise ManifestError(
                        "model.source_not_allowlisted", "model source domain is not allowlisted"
                    )
            if asset.id in assets:
                raise ManifestError("model.id_duplicate", "model id is duplicated")
            assets[asset.id] = asset
        return cls(assets)

    def get(self, model_id: str) -> ModelAsset:
        try:
            return self._assets[model_id]
        except KeyError as exc:
            raise KeyError(f"unknown model: {model_id}") from exc

    def all(self) -> tuple[ModelAsset, ...]:
        return tuple(self._assets.values())
