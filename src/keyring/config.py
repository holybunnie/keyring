from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from .models import ProbeConfig, StrategyConfig


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class LoadedConfig:
    path: Path
    sha256: str
    model: BaseModel


def _load(path: Path, model_type: type[ModelT]) -> LoadedConfig:
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    document = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return LoadedConfig(path=path, sha256=checksum, model=model_type.model_validate(document))


def load_probe_config(path: str | Path = "config/probes.yaml") -> LoadedConfig:
    loaded = _load(Path(path), ProbeConfig)
    return loaded


def load_strategy_config(path: str | Path = "config/strategy.yaml") -> LoadedConfig:
    loaded = _load(Path(path), StrategyConfig)
    return loaded
