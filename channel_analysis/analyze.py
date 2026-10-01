"""動画ごとの構造分類 (分析レイヤー)。

meta.json + transcript.txt (利用者が権利を持つ/許諾を得たテキスト) を LLM に渡し、
動画の構造を JSON で分類する。動画本文の逐語抜粋は出力にも保存にも含めない。

- hook_pattern        冒頭の型 (ラベル)
- title_pattern       タイトル構造の分類
- body_structure      本編の章立て要約
- script_density      1-5 score (1分あたりの新情報密度)
- cta_pattern         誘導先の型
- knowhow_claims      動画内の主張の要約 (原文を転記せず言い換える)
- viral_factors       伸びた要因の仮説
- structural_notes    構造上の観察 (max 7)

結果は SQLite (video_analysis テーブル) に upsert される。

LLM 呼び出しは `src/claude_cli.py` (スタブ) 経由。利用者の環境に合わせて実装する。
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from _dotenv import load_dotenv  # noqa: E402

load_dotenv()

# claude_cli は "haiku" / "sonnet" / "opus" alias を受け付ける想定(スタブの契約)
DEFAULT_MODEL = os.environ.get("ANALYZER_MODEL", "haiku")

ANALYZE_SYSTEM = """あなたは YouTube 動画の構造を分類するアナリストです。
動画 (タイトル + 説明文 + 利用者が提供したテキスト) を読み、
構成上の型を分類・要約して構造化します。

ルール:
- 動画内の文を逐語で出力に写さない。要約と分類ラベルだけを返す
- 主張は言い換えて要約し、根拠の種類 (データ / 事例 / 引用 / 主張のみ) を付ける
- 数値・期間は具体に
- 出力は厳密な JSON のみ (前置き禁止、 ```json フェンス禁止)
"""

ANALYZE_USER_TEMPLATE = """# 動画情報

タイトル: {title}
URL: https://www.youtube.com/watch?v={video_id}
公開日: {published_at}
尺(秒): {duration_sec}
再生数: {view_count}
高評価: {like_count}
コメント数: {comment_count}

# 説明文 (冒頭1500字)

{description}

# 利用者提供テキスト

{transcript}

# 出力スキーマ (厳密に従え)

```jsonschema
{{
  "hook_pattern": "問題提起 | 数値ショック | 逆説 | 結論先出し | ターゲット呼びかけ | 体験談 | 否定・煽り | 公式情報引用 | その他",
  "title_pattern": "数字+体言止め / 対比 / 煽り疑問 / 否定/警告 / 公式権威付け / 期間限定 / ターゲット明示 などの分類ラベル + 一言補足",
  "body_structure": "本編の章立てを 3-7 ポイントで時系列に要約(箇条書きを 1行ずつ \\n で区切る、 各40字以内)",
  "script_density": 1,
  "cta_pattern": "誘導先と誘導タイミングの型(概要欄/別動画/メンバーシップ 等)",
  "knowhow_claims": [
    {{
      "claim": "主張の要約1行(60字以内、言い換え)",
      "evidence_type": "データ | 事例 | 引用 | 主張のみ"
    }}
  ],
  "viral_factors": ["伸びた要因の仮説 (最大5個、 1行40字以内)"],
  "structural_notes": ["構造上の観察 (最大7個、 1行60字以内)"]
}}
```

script_density は 1-5 の整数:
  1=雑談ベース  2=情報希薄  3=普通  4=高密度  5=情報の畳掛け
"""


def _load_video_inputs(video_dir: Path) -> dict[str, Any]:
    meta = json.loads((video_dir / "meta.json").read_text(encoding="utf-8"))
    transcript_path = video_dir / "transcript.txt"
    transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
    return {"meta": meta, "transcript": transcript}


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n…(以降 {len(text) - max_chars} 字省略)"


def analyze_video(
    video_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
    max_transcript_chars: int = 60000,
) -> dict[str, Any]:
    """1動画を分析して dict を返す。

    dict は video_analysis テーブルの全カラムを含む (+ raw_response)。
    LLM 失敗時は例外を上げる (呼び出し側で catch)。
    """
    inputs = _load_video_inputs(video_dir)
    meta = inputs["meta"]
    transcript = inputs["transcript"].strip()

    if not transcript:
        raise RuntimeError(f"transcript empty: {video_dir.name}")

    transcript_chars = len(transcript)
    transcript_for_prompt = _truncate(transcript, max_transcript_chars)
    description = _truncate(meta.get("description", "") or "", 1500)

    # view_count 等は meta.json には無いので、 呼び出し側が `_view_count` などのキーで渡す。
    prompt = ANALYZE_USER_TEMPLATE.format(
        title=meta.get("title", ""),
        video_id=meta.get("video_id", video_dir.name),
        published_at=meta.get("published_at", "")[:10],
        duration_sec=meta.get("duration_sec", 0),
        view_count=meta.get("_view_count", "(不明)"),
        like_count=meta.get("_like_count", "(不明)"),
        comment_count=meta.get("_comment_count", "(不明)"),
        description=description,
        transcript=transcript_for_prompt,
    )

    from claude_cli import run_claude_cli, parse_json_loose
    raw = run_claude_cli(
        ANALYZE_SYSTEM,
        prompt,
        model=model,
        tools=None,
        timeout=240,
    )
    try:
        parsed = parse_json_loose(raw)
    except ValueError as e:
        raise RuntimeError(f"LLM JSON parse failed: {e}\nraw[:500]={raw[:500]}")

    # 必須キー検証
    required = [
        "hook_pattern", "title_pattern", "body_structure",
        "script_density", "cta_pattern", "knowhow_claims", "viral_factors",
        "structural_notes",
    ]
    missing = [k for k in required if k not in parsed]
    if missing:
        raise RuntimeError(f"LLM response missing keys: {missing}")

    return {
        "video_id": meta.get("video_id", video_dir.name),
        "model": model,
        "transcript_chars": transcript_chars,
        "hook_pattern": parsed["hook_pattern"],
        "title_pattern": parsed["title_pattern"],
        "body_structure": parsed["body_structure"],
        "script_density": int(parsed["script_density"]),
        "cta_pattern": parsed["cta_pattern"],
        "knowhow_claims": json.dumps(parsed["knowhow_claims"], ensure_ascii=False),
        "viral_factors": json.dumps(parsed["viral_factors"], ensure_ascii=False),
        "structural_notes": json.dumps(parsed["structural_notes"], ensure_ascii=False),
        # 生の LLM 応答は保存しない(逐語の混入を避ける)。パース済みの JSON 文字列だけを残す。
        "raw_response": json.dumps(parsed, ensure_ascii=False),
    }
