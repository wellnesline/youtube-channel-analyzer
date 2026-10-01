# youtube-channel-analyzer

Read-only analysis toolkit for YouTube channels: fetch public metadata and comments through the official Data API, ingest texts you are entitled to use, store everything in SQLite, and classify the structure of each video (hook type, title pattern, outline, density) with an LLM.

YouTube チャンネルの公開情報（公式 API）を集めて SQLite に蓄積し、動画ごとの構成・フックの型・タイトルの型などを LLM で分類する分析基盤です。公開用に整理したサンプル実装です。

## 概要

「伸びている動画は何が違うのか」を感覚でなく表にして比べるための基盤です。取得（API）→ テキストの取り込み → 保存（SQLite + ファイル）→ 分析（LLM）の層に分け、各段階を再開できるようにしています。分析結果は、動画のメトリクスと並べて横断的に検索できます。

## 主な機能・設計のポイント

- **読み取り専用の API ラッパ（`yt_api.py`）**: YouTube Data API v3 の公開情報だけを読みます。コメントは本文と件数のみを使い、投稿者の名前や ID は保存しません。API の消費量（units）を意識した呼び出しにしています
- **テキストの取り込み（`transcribe.py`）**: 音声や字幕の自動取得は行いません。入力は、利用者が自分で用意した（権利を持つ、または権利者から許諾を得た）テキストファイルだけで、`rights_confirmed=True` を明示しない呼び出しは拒否します
- **保存層（`db.py` / `paths.py`）**: 動画・メトリクスの時系列スナップショット・取得ログ・分析結果の各テーブル。動画本文（取り込んだテキスト・コメント）はファイル側に置き、DB は索引と時系列に専念させます。取得ログがあるため、未処理の動画だけを選んで再開できます
- **構造の分類（`analyze.py`）**: メタ情報・取り込んだテキスト・コメントを LLM に渡し、冒頭の型（ラベル）、タイトル構造、本編の骨子、情報密度のスコア、CTA の型、動画内の主張の要約（言い換え）、構造上の観察などを JSON で抽出します。動画内の文を逐語で出力・保存しないようプロンプトで指示し、生の応答は保存せずパース済みの JSON だけを upsert します
- **LLM 呼び出しの分離**: LLM 呼び出しは `src/claude_cli.py` のインターフェースに分離しています（同梱はスタブ）。使うモデルは `ANALYZER_MODEL` で切り替えます
- **設定駆動**: 分析対象チャンネルは `registry.yaml` で与え、データの置き場は `ANALYZER_DATA_DIR`（既定は `analysis_data/`）で変えられます

## ディレクトリ構成（主要ファイル）

```
youtube-channel-analyzer/
├ channel_analysis/
│  ├ yt_api.py        YouTube Data API ラッパ（読み取り専用）
│  ├ transcribe.py    利用者提供テキストの取り込み
│  ├ db.py  paths.py  registry.py     SQLite スキーマ・パス・設定
│  └ analyze.py       構造の分類（LLM）
├ src/claude_cli.py  src/_dotenv.py     ← 合成スタブ
└ requirements.txt
```

## 動かし方

- 必要なもの: Python 3、`requirements.txt` の依存
- 環境変数: `YOUTUBE_API_KEY`（公開情報の取得）、`YT_TOKEN_PATH`（任意。youtube.readonly の OAuth トークンのパス）、`ANALYZER_MODEL`、`ANALYZER_DATA_DIR`
- 設定: `registry.yaml`（分析対象の一覧）と、チャンネルごとの `channel.yaml` をデータ置き場に用意します（同梱していません）
- LLM 連携: `src/claude_cli.py` は呼び出しインターフェースだけのスタブです。自分の環境の LLM 呼び出しに合わせて `run_claude_cli()` を実装してください

## 制限事項（閉包）

`ast` と import 文の調査で、リポジトリ内・標準ライブラリ・`requirements.txt` のいずれにも無い import はありません（`google.*` は Google 系パッケージで解決されます）。

- **合成スタブ（2 件）**: `src/claude_cli.py`（LLM 呼び出しのインターフェースのみ）, `src/_dotenv.py`（最小の .env ローダ）
- **他の公開リポジトリへの依存**: なし
- **非同梱の実行時データ**: `registry.yaml`, チャンネル別の `channel.yaml`, OAuth トークン、取得済みのメタデータ・取り込んだテキスト・コメント・SQLite（`.gitignore` で除外しています）
- 外部サービス: YouTube Data API（`YOUTUBE_API_KEY`）。他の外部サービスへ動画の音声やテキストを送る処理は含みません
- 取得したデータは YouTube API サービスの規約の範囲で保存し、保存期間も規約に従ってください（保存期間は利用者が管理します。古いスナップショットの削除処理は同梱していません）。
- 利用範囲: 公開情報の読み取りに限り、YouTube API サービス利用規約と各コンテンツの権利者の許諾の範囲で使ってください。取り込むテキストは、自分が権利を持つ動画、または利用許諾を得た動画のものに限ります。認証情報はリポジトリの外に置くことを勧めます

## ライセンス

All rights reserved. 閲覧目的で公開しています。詳細は [LICENSE](LICENSE) を参照。
