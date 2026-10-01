"""動画ID → transcript.txt の取り込み。

このモジュールは YouTube から音声・字幕を自動取得しない。文字起こしの入力は、
利用者が自分で用意したテキストファイルに限る。

利用範囲: 自分が権利を持つ動画、または権利者から利用許諾を得た動画のテキストだけを入力すること。
`rights_confirmed=True` を明示しない呼び出しは拒否する。テキストは分析のために手元へ置くだけで、
再配布や公開はしない。
"""
from __future__ import annotations
from pathlib import Path


class RightsNotConfirmed(RuntimeError):
    """利用者が入力テキストの権利/許諾を確認していない。"""


def ingest_transcript(
    video_id: str,
    source_txt: Path,
    out_txt: Path,
    *,
    rights_confirmed: bool = False,
) -> int:
    """利用者が用意したテキスト `source_txt` を `out_txt` (transcript.txt) へ取り込む。

    戻り値は取り込んだ文字数。`rights_confirmed` が True でなければ何も書かずに例外を上げる。
    """
    if not rights_confirmed:
        raise RightsNotConfirmed(
            f"{video_id}: 入力テキストの権利/利用許諾を確認した上で rights_confirmed=True を渡してください"
        )
    source_txt = Path(source_txt)
    if not source_txt.is_file():
        raise FileNotFoundError(f"transcript source not found: {source_txt}")
    text = source_txt.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"transcript source is empty: {source_txt}")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(text + "\n", encoding="utf-8")
    print(f"[transcript] ingested {source_txt.name} -> {out_txt.name}  ({len(text)} chars)")
    return len(text)
