"""registry.yaml と channel.yaml の読み込み。"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import REGISTRY_YAML, channel_yaml


@dataclass
class ChannelConfig:
    slug: str
    channel_id: str
    channel_name: str = ""
    genre: list[str] = field(default_factory=list)
    enabled: bool = True
    fetch_priority: str = "medium"
    filter: dict[str, Any] = field(default_factory=dict)
    observation_axes: list[str] = field(default_factory=list)
    viral_threshold: dict[str, float] = field(default_factory=dict)

    @property
    def min_views(self) -> int:
        return int(self.filter.get("min_views") or 0)

    @property
    def max_age_days(self) -> int | None:
        v = self.filter.get("max_age_days")
        return int(v) if v else None

    @property
    def exclude_shorts(self) -> bool:
        return bool(self.filter.get("exclude_shorts"))


def load_registry() -> list[dict[str, Any]]:
    """registry.yaml の channels 配列を返す。"""
    if not REGISTRY_YAML.exists():
        return []
    data = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8")) or {}
    return data.get("channels") or []


def load_channel(slug: str) -> ChannelConfig:
    """`<データ置き場>/<slug>/channel.yaml` を読み、 registry の entry とマージ。"""
    yml = channel_yaml(slug)
    if not yml.exists():
        raise FileNotFoundError(f"channel.yaml not found: {yml}")
    detail = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}

    # registry の同一 slug entry を上書きベースに使う
    base: dict[str, Any] = {}
    for entry in load_registry():
        if entry.get("slug") == slug:
            base = dict(entry)
            break

    merged = {**base, **detail}
    return ChannelConfig(
        slug=merged["slug"],
        channel_id=merged["channel_id"],
        channel_name=merged.get("channel_name", ""),
        genre=list(merged.get("genre") or []),
        enabled=bool(merged.get("enabled", True)),
        fetch_priority=str(merged.get("fetch_priority", "medium")),
        filter=dict(merged.get("filter") or {}),
        observation_axes=list(merged.get("observation_axes") or []),
        viral_threshold=dict(merged.get("viral_threshold") or {}),
    )


def iter_enabled_channels() -> list[ChannelConfig]:
    """registry.yaml で enabled=true の全 ch を ChannelConfig として返す。"""
    out: list[ChannelConfig] = []
    for entry in load_registry():
        if not entry.get("enabled", True):
            continue
        slug = entry.get("slug")
        if not slug:
            continue
        try:
            out.append(load_channel(slug))
        except FileNotFoundError:
            # channel.yaml 未作成のものはスキップ(registry だけに entry がある状態)
            continue
    return out
