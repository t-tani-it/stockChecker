# stockChecker アーキテクチャマインドマップ

```mermaid
mindmap
  root((stockChecker))
    エントリポイント
      app.py
        Streamlit UI
        バックテスト実行
        タブレンダリング
      seed.py
        初期シード
        10銘柄DL
    設定
      config.py
        DB_PATH
        APIキー
        パラメータ
    Data Layer
      db/schema.py
        get_connection
        init_db
        7テーブル定義
        log_error
      db/tickers.py
        JPX東証
        S&P500
        Curated US
      db/downloader_prices.py
        初回一括DL
        差分更新
        save_prices
      db/downloader_financials.py
        yfinance
        EDINET日本
        extract_fiscal_year
        save_financials
      db/downloader_sentiment.py
        NewsAPI
        Finnhub
        FinBERT分析
    Rule Layer
      rules/base.py
        BaseRule基底
        normalize_score
        get_prices
        get_financial
      rules/runner.py
        discover_rules
        run_backtest
        save_results
      rules/momentum.py
        3/6/12ヶ月加重
      rules/value.py
        PER PBR 配当
      rules/quality.py
        ROE 自己資本 営業利益率
      rules/size.py
        時価総額5段階
      rules/low_vol.py
        年率ボラティリティ
      rules/pead.py
        決算サプライズ率
      rules/sentiment.py
        ニュースセンチメント
      rules/text_score.py
        決算書テキスト特徴
      rules/anomaly.py
        出来高急増
        ボラティリティ急増
    UI Layer
      ui/tabs.py
        ルール別タブ
        総合ランキングタブ
        チャート操作
      ui/charts.py
        Pillow PNG Candlestick
        20MA
        出来高
      ui/ranking.py
        総合スコア計算
        ランキング構築
    テスト
      tests/test_schema.py
        DBテーブル作成
        Ticker CRUD
        Price UPSERT
        Error Log
      tests/test_rules.py
        全9ルール0-100
        ルール自動発見
        バックテスト実行
        ランキング構築
    データベース
      backtest.db SQLite
        tickers
        prices
        financials
        indicators
        backtest_results
        sentiment_download_log
        error_log
```

## 凡例

| レイヤー | 役割 |
|----------|------|
| **エントリポイント** | アプリケーション起動・初期化 |
| **設定** | 環境変数による全パラメータ管理 |
| **Data Layer** | DB接続・スキーマ・データ取得（株価・財務・センチメント） |
| **Rule Layer** | プラグイン方式の9つの定量ルール + 実行エンジン |
| **UI Layer** | Streamlitによる可視化（タブ・チャート・ランキング） |
| **テスト** | pytest による自動テスト |
| **データベース** | SQLite 7テーブルによる永続化 |
