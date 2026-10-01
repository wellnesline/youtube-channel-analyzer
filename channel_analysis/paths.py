"""channel_analysis/ 配下のパス解決ユーティリティ。

データの置き場は環境変数 ANALYZER_DATA_DIR で変えられる(既定: リポジトリ直下の analysis_data/)。
"""
from __future__ import annotations
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("ANALYZER_DATA_DIR") or (REPO_ROOT / "analysis_data"))
REGISTRY_YAML = DATA_ROOT / "registry.yaml"
DB_PATH = DATA_ROOT / "db.sqlite"


def channel_dir(slug: str) -> Path:
    return DATA_ROOT / slug


def channel_yaml(slug: str) -> Path:
    return channel_dir(slug) / "channel.yaml"


def videos_dir(slug: str) -> Path:
    return channel_dir(slug) / "videos"


def video_dir(slug: str, video_id: str) -> Path:
    return videos_dir(slug) / video_id


def reports_dir(slug: str) -> Path:
    return channel_dir(slug) / "reports"


def ensure_video_dir(slug: str, video_id: str) -> Path:
    d = video_dir(slug, video_id)
    d.mkdir(parents=True, exist_ok=True)
    return d
