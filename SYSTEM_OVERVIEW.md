# stockChecker — 株式投資「法則」バックテストシステム

資産運用・株式投資を対象としたデータマイニングで発見された「法則（＝利益に繋がる株価パターンや財務条件）」を、過去データを使って検証（バックテスト）するためのツール。

## 対象ユーザー

- データマイニングによって発見した投資法則を確認・検証したい個人投資家
- AIエージェント（本ドキュメントを読んでシステムを操作する）

## 前提環境

| 要件 | バージョン |
|------|-----------|
| Python | 3.11+ |
| pip | 最新推奨 |

依存パッケージは `requirements.txt` に記載されています。

## インストール

```bash
# 依存パッケージのインストール
pip install -r requirements.txt
```

### APIキーの設定（オプション）

センチメント分析（ニュース感情分析）を利用する場合のみ、`.env` ファイルをプロジェクトルートに作成し、以下を設定してください。

```
NEWSAPI_KEY=your_newsapi_key
FINNHUB_API_KEY=your_finnhub_key
```

- [NewsAPI](https://newsapi.org/register) — 無料枠: 1日100リクエスト
- [Finnhub](https://finnhub.io/register) — 無料枠: 1分60リクエスト

APIキーが未設定の場合、センチメント関連ルールは中立スコア（50.0）を返します。

## クイックスタート

```bash
# 0. プロジェクトフォルダへ移動
cd stockChecker

# 1. 仮想環境を有効化（必要な場合）
conda activate backtest

# 2. データベースの初期化＋デモデータ投入（10銘柄: AAPL, MSFT, GOOGL 等）
python seed.py

# 3. Streamlit アプリ起動
streamlit run app.py

# 4. ブラウザが開いたら、基準日を選択して「バックテスト実行」ボタンを押下
```

### 全データのダウンロード（任意）

seed.py は10銘柄のみを対象としています。**全銘柄（US 503 + 日本 3,716）**を対象とする場合は以下のスクリプトを実行します。

`download_full.py` は market 引数とデータ種別フラグでダウンロード範囲を柔軟に指定できます。

```bash
# 全market × 全データ種別（株価 + 財務 + PEAD + センチメント）
python download_full.py

# US株のみ × 全データ種別
python download_full.py us

# 日本株のみ × 株価 + 財務
python download_full.py japan --price --financials

# 日本株の株価のみ
python download_full.py japan --price

# PEAD のみ（デフォルト market=all）
python download_full.py --pead

# センチメントのみ（US株）
python download_full.py us --sentiment

# インクリメンタル（差分更新）: 株価のみ
python download_full.py --incremental

# US株の株価を差分更新
python download_full.py us --inc

# 全marketの財務データを差分更新
python download_full.py --incremental --financials

# US株の株価＋センチメントを差分更新
python download_full.py us --inc --price --sentiment
```

| market | 対象 |
|--------|------|
| `all`（デフォルト） | US株 + 日本株 |
| `us` | US株のみ |
| `japan` | 日本株のみ |

| フラグ | データ種別 |
|--------|-----------|
| `--price` | 株価（yfinance、10年分） |
| `--financials` | 財務データ（yfinance／EDINET） |
| `--pead` | PEAD（決算サプライズ） |
| `--sentiment` | センチメント（ニュース感情分析） |
| `--incremental` / `--inc` | 差分更新モード（各データ種別の未取得分のみ処理） |
| （未指定） | 全て |

#### 日本株の初回ダウンロード手順

```bash
# 1. 銘柄リスト更新（自動）
python download_full.py japan --price

# 2. 株価完了後、財務データ
python download_full.py japan --financials

# 3. PEAD 事前計算
python download_full.py japan --pead

# 4. センチメント（複数回に分けて実行）
python download_full.py japan --sentiment
```

#### センチメントのダウンロード

センチメント分析（ニュース感情分析）は [NewsAPI](https://newsapi.org/register) の無料枠（1日100リクエスト）の制限があるため、全銘柄を複数回に分けて取得する必要があります。1回の実行で最大50銘柄を処理し、前回のダウンロードから24時間経過していない銘柄は自動スキップされます。

```bash
# 1回目: 50銘柄を処理（本日）
python download_full.py us --sentiment

# 翌日以降、同じコマンドを繰り返し実行
python download_full.py us --sentiment   # 2回目
python download_full.py us --sentiment   # 3回目
# ... 全銘柄完了するまで繰り返し
```

進捗は `sentiment_download_log` テーブルで管理され、中断しても次回は続きから自動再開します。

#### PEAD（決算サプライズ）の事前計算

PEADルール（決算発表後ドリフト）は yfinance API から各銘柄の決算サプライズ率を取得します。初回は対象銘柄数分のAPI呼び出しが発生するため、以下のコマンドで事前計算しておくことを推奨します。

```bash
# 全銘柄の PEAD を一括計算
python download_full.py --pead

# US株のみ
python download_full.py us --pead

# 日本株のみ
python download_full.py japan --pead
```

1回の実行で `indicators` テーブルに保存され、以降のバックテストでは DB から読み込むため高速に動作します。再計算したい場合は再度同じコマンドを実行してください。

#### インクリメンタル（差分更新）モード

`--incremental`（短縮: `--inc`）フラグを指定すると、各データ種別の「未取得分のみ」を処理します。

```bash
# 株価の差分更新（最終取得日より後のデータのみ取得）
python download_full.py --incremental

# 財務データの差分更新（最新会計年度が未取得の銘柄のみ）
python download_full.py --incremental --financials

# PEADの差分更新（今年度のPEADが未計算の銘柄のみ）
python download_full.py --incremental --pead

# センチメントの差分更新（次回DL時刻を過ぎた銘柄のみ）
python download_full.py --incremental --sentiment
```

**動作仕様:**

| データ種別 | 差分更新の条件 |
|-----------|---------------|
| price | 最終取得日が当日より古い銘柄を再取得（5日バッファ付き） |
| financials | financials テーブルの最新 fiscal_year が前年度未満の銘柄のみ |
| pead | indicators テーブルに今年度の PEAD スコアがない銘柄のみ |
| sentiment | sentiment_download_log の next_download_at を超過した銘柄のみ（従来挙動） |

`--incremental` 単独（種別未指定）の場合は株価の差分更新のみ実行します。
複数種別を同時に指定することも可能です（例: `--inc --price --pead`）。

## システム構成

```
stockChecker/
├── app.py                     # Streamlit メインエントリポイント
├── config.py                  # 設定（環境変数読み込み）
├── seed.py                    # 初期データ投入スクリプト（10銘柄）
├── download_full.py            # 全銘柄（US + 日本）一括ダウンロードスクリプト
├── requirements.txt           # 依存パッケージ一覧
├── backtest.db                # SQLite データベース
│
├── db/                        # データ層
│   ├── schema.py              # テーブル定義（7テーブル）
│   ├── tickers.py             # 銘柄リスト管理（S&P500 / JPX）
│   ├── downloader_prices.py   # 株価ダウンロード（yfinance）
│   ├── downloader_financials.py # 財務データDL（yfinance / EDINET）
│   └── downloader_sentiment.py  # ニュースDL + FinBERT 感情分析
│
├── rules/                     # ルール層（プラグイン形式）
│   ├── base.py                # 抽象基底クラス
│   ├── momentum.py            # モメンタム
│   ├── value.py               # バリュー（割安）
│   ├── quality.py             # クオリティ（高品質）
│   ├── size.py                # サイズ（小型株）
│   ├── low_vol.py             # 低ボラティリティ
│   ├── pead.py                # PEAD（決算サプライズ後ドリフト）
│   ├── sentiment.py           # ニュースセンチメント
│   ├── text_score.py          # 決算書テキスト特徴
│   └── anomaly.py             # 異常検知（出来高・ボラティリティ急変）
│
├── ui/                        # UI層
│   ├── tabs.py                # タブレンダリング
│   ├── ranking.py             # ランキング集計
│   └── charts.py              # Plotly チャート（ローソク足・MA・出来高）
│
├── tests/                     # テスト
│   ├── test_schema.py
│   └── test_rules.py
│
├── docs/                      # 詳細ドキュメント
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── INTERFACE.md
│   ├── OPERATION_RULES.md
│   ├── WORKFLOW.md
│   ├── TEST_CASES.md
│   ├── DIAGRAMS.md
│   └── MEMORY_GUIDE.md
│
└── diagrams/                  # Mermaid 図解
    ├── 01_flowchart.mmd
    ├── 02_sequence.mmd
    ├── 03a_class_rules.mmd
    ├── 03b_class_modules.mmd
    ├── 04_mindmap.mmd
    └── 05_state.mmd
```

## システムの構成要素

### データ層（db/）

- 株価データ（yfinance）
- 財務データ（米国株: yfinance、日本株: edinet）
- ニュース/決算テキスト（NewsAPI/Finnhub/edinet/SEC-EDGAR → FinBERT分析）
- SQLite データベースに蓄積保存

### ルール層（rules/）

9種類の「法則」をプラグインとして実装（全9ルール）:

| ルール | 説明 | 必要データ |
|--------|------|-----------|
| モメンタム | 過去3〜12ヶ月リターンの加重平均 | 株価のみ |
| バリュー | PER・PBR・配当利回りで割安度評価 | 財務データ |
| クオリティ | ROE・自己資本比率・営業利益率で品質評価 | 財務データ |
| サイズ | 時価総額で小型株ほど高スコア | 時価総額 |
| 低ボラティリティ | 年率換算ヒストリカルボラティリティ | 株価のみ |
| PEAD | 決算サプライズ率でポジティブサプライズを評価 | yfinance API |
| センチメント | FinBERT によるニュース感情分析スコア | センチメント指標 |
| テキスト特徴 | 決算書テキストの楽観性スコア（ROE フォールバック） | テキスト指標 + 財務 |
| 異常検知 | 出来高・ボラティリティ急増を検出 | 株価のみ |

新法則は `rules/base.py` の `BaseRule` を継承し、`rules/` 配下にファイルを置くだけで自動認識されます（プラグイン方式）。

### UI層（ui/ + app.py）

- Streamlit による Web アプリケーション
- タブ形式で各法則の適合銘柄を表示（上位50銘柄）
- 総合ランキングタブで全法則クロス集計（上位10銘柄）
- Plotly による株価チャート表示（ローソク足 + 移動平均線 + 出来高、3/6/9/12ヶ月切替）

## データソース

| データ種別 | 米国株 | 日本株 |
|-----------|--------|--------|
| 株価 | yfinance | yfinance |
| 財務データ | yfinance（蓄積） | edinet |
| 決算書テキスト | SEC EDGAR (sec-edgar-api) | edinet |
| ニュース | NewsAPI / Finnhub + FinBERT | NewsAPI / Finnhub + FinBERT |

## データベース（SQLite）

7つのテーブルで構成:

| テーブル | 用途 |
|----------|------|
| tickers | 銘柄マスタ（シンボル・市場・時価総額） |
| prices | 日次株価（始値・高値・安値・終値・出来高） |
| financials | 会計年度別財務データ |
| indicators | ルール別事前計算済み指標（センチメント等） |
| backtest_results | バックテスト実行結果 |
| sentiment_download_log | センチメントDL履歴（API制限制御） |
| error_log | エラーログ |

## 非機能要件

- 日本株 + 米国株 合計約10,000〜12,000銘柄
- 財務データは4年制限があるため、DBに蓄積して拡張
- センチメントDLはAPI制限を考慮し、銘柄を順次処理（前回DLから24時間以上経過したもののみ）

## ドキュメント

詳細は `docs/` フォルダに格納しています。

| ドキュメント | 内容 |
|-------------|------|
| ARCHITECTURE.md | アーキテクチャ全体図（マインドマップ） |
| DATA_MODEL.md | DBスキーマ・7テーブル定義・成長イメージ |
| INTERFACE.md | UI構成・操作手順・プラグイン追加方法 |
| OPERATION_RULES.md | 運用ルール・禁止行為・API制限対応 |
| WORKFLOW.md | 業務フロー・処理フロー（全5種） |
| TEST_CASES.md | テストケース一覧・検証チェックリスト |
| DIAGRAMS.md | 図解一覧（フローチャート/シーケンス/クラス/状態） |
| MEMORY_GUIDE.md | AIエージェント用 記憶構造・運用状態管理 |

## ライセンス

MIT
