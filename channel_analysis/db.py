"""SQLite スキーマ + 接続管理。

横断クエリ(再生数ランキング, チャンネル間の構造比較等)用。 動画別本文(transcript/comments)は
ファイルシステム側に置き、 DB は インデックス + 時系列メトリクス に専念する。
取得したデータは YouTube API サービスの規約の範囲で保存する(保存期間を含む。保存期間は規約に従って利用者が管理する。古いスナップショットの削除処理は同梱していない)。
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from .paths import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id          TEXT PRIMARY KEY,
    channel_slug      TEXT NOT NULL,
    channel_id        TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT,
    published_at      TEXT NOT NULL,             -- ISO8601
    duration_sec      INTEGER,                   -- ISO8601 PT...S を秒に変換済
    is_short          INTEGER DEFAULT 0,         -- duration<60 のヒューリスティック
    tags              TEXT,                      -- JSON array
    thumb_url         TEXT,
    first_seen_at     TEXT NOT NULL,             -- このDBで初観測した日付
    last_fetched_at   TEXT NOT NULL,
    -- 最新値(stats_snapshots から重複だが頻繁にクエリされるので冗長保持)
    view_count        INTEGER DEFAULT 0,
    like_count        INTEGER DEFAULT 0,
    comment_count     INTEGER DEFAULT 0,
    transcript_status TEXT DEFAULT 'pending'     -- pending / done / skipped / failed (done = 利用者が提供したテキストを取り込み済み)
);

CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_slug, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_views ON videos(channel_slug, view_count DESC);

CREATE TABLE IF NOT EXISTS stats_snapshots (
    video_id          TEXT NOT NULL,
    snapshot_date     TEXT NOT NULL,             -- YYYY-MM-DD
    view_count        INTEGER NOT NULL,
    like_count        INTEGER NOT NULL,
    comment_count     INTEGER NOT NULL,
    PRIMARY KEY (video_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON stats_snapshots(snapshot_date);

CREATE TABLE IF NOT EXISTS fetch_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_slug      TEXT NOT NULL,
    stage             TEXT NOT NULL,             -- meta / comments / transcribe / rank / analyze
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    videos_processed  INTEGER DEFAULT 0,
    error             TEXT
);

-- 分析レイヤー: 動画ごとの構造分類の結果(動画本文の逐語は保存しない)
CREATE TABLE IF NOT EXISTS video_analysis (
    video_id            TEXT PRIMARY KEY,
    channel_slug        TEXT NOT NULL,
    analyzed_at         TEXT NOT NULL,
    model               TEXT NOT NULL,
    transcript_chars    INTEGER,
    hook_pattern        TEXT,                    -- ラベル: 問題提起 / 数値ショック / 逆説 / 結論先出し / ターゲット呼びかけ / 体験談 / その他
    title_pattern       TEXT,                    -- タイトル構造ラベル
    body_structure      TEXT,                    -- 章立ての要約 (本編構成)
    script_density      INTEGER,                 -- 1-5: 1分あたり新情報密度
    cta_pattern         TEXT,                    -- どこへ誘導しているか
    knowhow_claims      TEXT,                    -- JSON array: [{claim(要約), evidence_type}]
    viral_factors       TEXT,                    -- JSON array: 伸びた要因の仮説
    structural_notes    TEXT,                    -- JSON array: 構造上の観察 (max 7)
    raw_response        TEXT                     -- パース済み JSON (生の応答は保存しない)
);

CREATE INDEX IF NOT EXISTS idx_analysis_channel ON video_analysis(channel_slug);
"""


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- videos ----------

def upsert_video(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    channel_slug: str,
    channel_id: str,
    title: str,
    description: str,
    published_at: str,
    duration_sec: int | None,
    is_short: bool,
    tags: str,
    thumb_url: str,
    view_count: int,
    like_count: int,
    comment_count: int,
) -> None:
    today = date.today().isoformat()
    conn.execute(
        """
        INSERT INTO videos (
            video_id, channel_slug, channel_id, title, description,
            published_at, duration_sec, is_short, tags, thumb_url,
            first_seen_at, last_fetched_at,
            view_count, like_count, comment_count
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
            title=excluded.title,
            description=excluded.description,
            duration_sec=excluded.duration_sec,
            is_short=excluded.is_short,
            tags=excluded.tags,
            thumb_url=excluded.thumb_url,
            last_fetched_at=excluded.last_fetched_at,
            view_count=excluded.view_count,
            like_count=excluded.like_count,
            comment_count=excluded.comment_count
        """,
        (
            video_id, channel_slug, channel_id, title, description,
            published_at, duration_sec, 1 if is_short else 0, tags, thumb_url,
            today, today,
            view_count, like_count, comment_count,
        ),
    )


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    view_count: int,
    like_count: int,
    comment_count: int,
    snapshot_date: str | None = None,
) -> None:
    snapshot_date = snapshot_date or date.today().isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO stats_snapshots
        (video_id, snapshot_date, view_count, like_count, comment_count)
        VALUES (?,?,?,?,?)
        """,
        (video_id, snapshot_date, view_count, like_count, comment_count),
    )


def list_videos(
    conn: sqlite3.Connection,
    channel_slug: str,
    *,
    order: str = "views",
    limit: int | None = None,
    min_views: int = 0,
) -> list[sqlite3.Row]:
    order_sql = {
        "views": "view_count DESC",
        "recent": "published_at DESC",
        "engagement": "(CAST(like_count AS REAL) + comment_count) / NULLIF(view_count, 0) DESC",
    }.get(order, "view_count DESC")
    sql = (
        "SELECT * FROM videos WHERE channel_slug = ? AND view_count >= ? "
        f"ORDER BY {order_sql}"
    )
    params: list[Any] = [channel_slug, min_views]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def update_transcript_status(
    conn: sqlite3.Connection, video_id: str, status: str
) -> None:
    conn.execute(
        "UPDATE videos SET transcript_status = ? WHERE video_id = ?",
        (status, video_id),
    )


def pending_transcript_videos(
    conn: sqlite3.Connection,
    channel_slug: str,
    *,
    min_views: int = 0,
    limit: int = 5,
) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT * FROM videos
        WHERE channel_slug = ?
          AND transcript_status = 'pending'
          AND view_count >= ?
        ORDER BY view_count DESC
        LIMIT ?
        """,
        (channel_slug, min_views, limit),
    ))


# ---------- video_analysis ----------

def upsert_video_analysis(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    channel_slug: str,
    model: str,
    transcript_chars: int,
    hook_pattern: str,
    title_pattern: str,
    body_structure: str,
    script_density: int,
    cta_pattern: str,
    knowhow_claims: str,
    viral_factors: str,
    structural_notes: str,
    raw_response: str,
) -> None:
    from datetime import datetime
    conn.execute(
        """
        INSERT INTO video_analysis (
            video_id, channel_slug, analyzed_at, model, transcript_chars,
            hook_pattern, title_pattern, body_structure, script_density,
            cta_pattern, knowhow_claims, viral_factors, structural_notes,
            raw_response
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
            analyzed_at=excluded.analyzed_at,
            model=excluded.model,
            transcript_chars=excluded.transcript_chars,
            hook_pattern=excluded.hook_pattern,
            title_pattern=excluded.title_pattern,
            body_structure=excluded.body_structure,
            script_density=excluded.script_density,
            cta_pattern=excluded.cta_pattern,
            knowhow_claims=excluded.knowhow_claims,
            viral_factors=excluded.viral_factors,
            structural_notes=excluded.structural_notes,
            raw_response=excluded.raw_response
        """,
        (
            video_id, channel_slug, datetime.utcnow().isoformat(), model, transcript_chars,
            hook_pattern, title_pattern, body_structure, script_density,
            cta_pattern, knowhow_claims, viral_factors, structural_notes,
            raw_response,
        ),
    )


def pending_analysis_videos(
    conn: sqlite3.Connection,
    channel_slug: str,
    *,
    limit: int = 20,
    min_views: int = 0,
) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT v.* FROM videos v
        LEFT JOIN video_analysis a ON v.video_id = a.video_id
        WHERE v.channel_slug = ?
          AND v.transcript_status = 'done'
          AND a.video_id IS NULL
          AND v.view_count >= ?
        ORDER BY v.view_count DESC
        LIMIT ?
        """,
        (channel_slug, min_views, limit),
    ))


# ---------- fetch_log ----------

def start_fetch(conn: sqlite3.Connection, channel_slug: str, stage: str) -> int:
    from datetime import datetime
    cur = conn.execute(
        "INSERT INTO fetch_log (channel_slug, stage, started_at) VALUES (?,?,?)",
        (channel_slug, stage, datetime.utcnow().isoformat()),
    )
    return cur.lastrowid or 0


def finish_fetch(
    conn: sqlite3.Connection, log_id: int, videos_processed: int, error: str | None = None
) -> None:
    from datetime import datetime
    conn.execute(
        "UPDATE fetch_log SET finished_at=?, videos_processed=?, error=? WHERE id=?",
        (datetime.utcnow().isoformat(), videos_processed, error, log_id),
    )
