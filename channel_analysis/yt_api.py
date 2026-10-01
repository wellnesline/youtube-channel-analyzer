"""YouTube Data API v3 のラッパー(チャンネル分析用、 読み取り専用)。

利用範囲: 公開情報の読み取りのみ。 YouTube API サービス利用規約・各コンテンツの権利者の許諾の範囲で使うこと。
コメント投稿者の名前・IDは保存しない(集計・傾向分析にはテキストと件数だけを使う)。

認証: API key(環境変数 YOUTUBE_API_KEY)を基本とする。OAuth token は任意で、パスを環境変数
YT_TOKEN_PATH に置いたときだけ使う(youtube.readonly scope のみ)。

クォータ目安:
- channels.list   : 1 unit / call
- playlistItems.list : 1 unit / call (50 videos/page)
- videos.list      : 1 unit / call (50 videos/page)
- commentThreads.list : 1 unit / call (100 comments/page)
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from _dotenv import load_dotenv  # noqa: E402

load_dotenv()


def _build_youtube(token_path: str | None = None):
    """YouTube Data API client を作る。

    環境変数 YT_TOKEN_PATH(または引数 token_path)に readonly scope の token があればそれを使い、
    無ければ API key 認証にフォールバックする。
    channels.list / playlistItems.list / videos.list はこちらで叩く。
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = token_path or os.environ.get("YT_TOKEN_PATH", "")
    # 分析は public read のみ。 OAuth token が無い/失効していても
    # API key 認証 client で channels/playlistItems/videos.list は全て叩けるため、
    # OAuth が使えない場合は API key にフォールバックする。
    try:
        if not token_path or not Path(token_path).exists():
            raise FileNotFoundError(f"OAuth token not configured or not found: {token_path or '(YT_TOKEN_PATH unset)'}")
        scopes = [
            "https://www.googleapis.com/auth/youtube.readonly",
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[yt_api] OAuth unavailable ({type(e).__name__}: {str(e)[:80]}); "
              f"falling back to API key for public read.", file=sys.stderr)
        return _build_youtube_apikey()


def _build_youtube_apikey():
    """API key 認証の YouTube Data API client。

    commentThreads.list は OAuth readonly scope で 403 が出ることがあるため、
    public コメント取得には API key 経由が安定。 .env の YOUTUBE_API_KEY を使う。
    """
    from googleapiclient.discovery import build

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY 未設定。 .env に YOUTUBE_API_KEY=AIza... を追加してください。 "
            "発行: https://console.cloud.google.com/apis/credentials"
        )
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


# ---------- channels ----------

def get_uploads_playlist_id(youtube, channel_id: str) -> str:
    """channels.list で uploads プレイリストIDを得る。 これを叩くと全アップロードを順に取れる。"""
    resp = youtube.channels().list(
        part="contentDetails", id=channel_id
    ).execute()
    items = resp.get("items") or []
    if not items:
        raise ValueError(f"channel not found: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def iter_uploads(
    youtube, uploads_playlist_id: str, max_pages: int = 20
) -> Iterator[dict[str, Any]]:
    """uploads プレイリストの全 item を yield(新しい順)。

    max_pages * 50 で件数上限。 初回 backfill は 20 page = 1000本まで。
    """
    page_token: str | None = None
    pages = 0
    while pages < max_pages:
        req = youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        )
        resp = req.execute()
        for item in resp.get("items") or []:
            yield item
        page_token = resp.get("nextPageToken")
        pages += 1
        if not page_token:
            break


# ---------- videos ----------

def get_videos_batch(youtube, video_ids: list[str]) -> list[dict[str, Any]]:
    """videos.list を 50件ずつバッチ取得。"""
    out: list[dict[str, Any]] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ).execute()
        out.extend(resp.get("items") or [])
    return out


_DUR_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_iso8601_duration(s: str) -> int:
    """PT1H2M3S → 3723 秒。"""
    m = _DUR_RE.match(s or "")
    if not m:
        return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def pick_thumb_url(snippet: dict[str, Any]) -> str:
    thumbs = (snippet.get("thumbnails") or {})
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbs:
            return thumbs[key].get("url", "")
    return ""


# ---------- comments ----------

def fetch_top_comments(
    youtube,
    video_id: str,
    *,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """commentThreads.list で likeCount 降順 top-N を取得。

    OAuth 経由だと readonly scope で 403 になることがあるため、
    こちらは API key 認証 client (`_build_youtube_apikey()`) を渡す前提。
    1 page = 100 が API 上限。 max_results > 100 なら追加 page を取りに行く。
    """
    out: list[dict[str, Any]] = []
    page_token: str | None = None
    while len(out) < max_results:
        try:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                order="relevance",
                maxResults=min(100, max_results - len(out)),
                textFormat="plainText",
                pageToken=page_token,
            ).execute()
        except Exception as e:
            msg = str(e)
            if "commentsDisabled" in msg or "disabled comments" in msg.lower():
                return []
            raise

        for item in resp.get("items") or []:
            top = item["snippet"]["topLevelComment"]["snippet"]
            out.append({
                "comment_id": item["id"],
                # 投稿者名は保存しない。 重複判定用に一方向ハッシュ(短縮)だけを残す
                "author_hash": hashlib.sha256(
                    top.get("authorDisplayName", "").encode("utf-8")
                ).hexdigest()[:12],
                "text": top.get("textDisplay", ""),
                "like_count": int(top.get("likeCount", 0)),
                "published_at": top.get("publishedAt", ""),
                "reply_count": int(item["snippet"].get("totalReplyCount", 0)),
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    out.sort(key=lambda c: c["like_count"], reverse=True)
    return out[:max_results]


# ---------- helpers ----------

def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
