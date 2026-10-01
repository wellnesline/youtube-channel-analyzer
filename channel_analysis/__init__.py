"""channel_analysis — YouTube チャンネルの公開情報を構造で分析する共通モジュール。

registry → fetch(公開メタデータ) → ingest(利用者が権利を持つ/許諾を得たテキスト) →
store(SQLite + ファイル) → analyze(構造の分類)。
"""
