# stockChecker 図解集

## 1. フローチャート — システム全体の処理フロー

```mermaid
flowchart TD
    A(["Start: streamlit run app.py"]) --> B[app.py: main]
    B --> C[db/schema.py: init_db<br>DB初期化]
    C --> C1[7テーブル作成<br>tickers, prices, financials,<br>indicators, backtest_results,<br>sentiment_download_log, error_log]
    C1 --> D[rules/runner.py: discover_rules<br>ルール動的発見]
    D --> D1[9ルール検出<br>Momentum, Value, Quality,<br>Size, LowVol, PEAD,<br>Sentiment, TextScore, Anomaly]
    D1 --> E[Streamlit UI レンダリング<br>日付選択 + Run Backtest ボタン]
    E --> F{"Run Backtest<br>クリック？"}
    F -->|No| E
    F -->|Yes| G[rules/runner.py: run_backtest]

    G --> H[全アクティブティッカー取得]
    H --> I{"次のルールは<br>あるか？"}
    I -->|Yes| J[ルールインスタンス生成]
    J --> K{"次のティッカーは<br>あるか？"}
    K -->|Yes| L{"need_financials?<br>(Value, Quality,<br>TextScore)"}

    L -->|True| M[DB: get_latest_financial<br>財務データ取得<br>PER, PBR, ROE, etc.]
    L -->|False| N[DB: get_prices / get_indicator<br>価格/指標データ取得]

    M --> O[calculate スコア 0-100]
    N --> O

    O --> P[スコア収集]
    P --> K

    K -->|No| Q[スコア降順ソート<br>ランク割当]
    Q --> R[backtest_results テーブル<br>に結果保存]
    R --> I

    I -->|No| S[compute_total_ranking<br>全ルールスコア合算]
    S --> T[Top10 総合ランキング]
    T --> U[結果をst.session_stateに保存]
    U --> V[UI タブ描画]
    V --> V1[タブ0: 総合ランキング<br>ティッカー名 + 内訳]
    V --> V2[タブ1-9: 各ルール<br>Top50 + スコア]
    V1 --> W["拡張: Plotlyチャート<br>3/6/9/12ヶ月選択<br>Candlestick + 20MA + Volume"]
    V2 --> W
    W --> E
```

---

## 2. シーケンス図 — バックテスト実行のモジュール間通信

```mermaid
sequenceDiagram
    actor User
    participant App as app.py
    participant Runner as rules/runner.py
    participant Rule as rules/*.py
    participant DB as db/schema (SQLite)

    User->>App: 日付選択 + Run Backtest クリック
    App->>App: discover_rules()<br>9ルールを動的検出

    App->>Runner: run_backtest(base_date)

    Runner->>DB: get_all_active_tickers()
    DB-->>Runner: List[ticker_id, symbol, name]

    rect rgb(232, 245, 255)
        Note over Runner,Rule: ルールループ (9回)
        Runner->>Rule: calculate(ticker_id, base_date)

        alt 財務データ型 (Value, Quality, TextScore)
            Rule->>DB: get_latest_financial(ticker_id, base_date)
            DB-->>Rule: fiscal_year, PER, PBR, ROE, etc.
        else 価格データ型 (Momentum, LowVol, Anomaly)
            Rule->>DB: get_prices(ticker_id, base_date, lookback_days)
            DB-->>Rule: DataFrame (OHLCV)
        else 指標参照型 (Sentiment, TextScore)
            Rule->>DB: get_indicator(ticker_id, date, rule_name)
            DB-->>Rule: pre_computed_score
        else 外部API型 (PEAD)
            Rule->>Rule: yfinance.Ticker(symbol).earnings_dates
            Note over Rule: 決算サプライズ率取得
        end

        Rule-->>Runner: score (float, 0-100)
    end

    Runner->>Runner: スコア降順ソート + ランク付与
    Runner->>DB: save_results(base_date, rule_name, scores)<br>INSERT OR REPLACE
    Runner->>Runner: compute_total_ranking()<br>全ルールスコア合算
    Runner-->>App: Dict[rule_name, List[ticker_id, score]]

    App->>App: st.session_state に保存
    App->>User: タブ表示 (総合 + 各ルール)

    User->>App: ティッカー展開 + 期間選択
    App->>DB: fetch_prices_for_chart(ticker_id, base_date, months)
    DB-->>App: DataFrame (OHLCV)
    App->>App: create_price_chart() → Plotly Figure
    App-->>User: Candlestick + 20MA + Volume 描画
```

---

## 3a. クラス図 — ルール継承階層（詳細）

`BaseRule`（抽象基底）と9つの具象ルールの完全なメソッドシグネチャ。A4横置き印刷に最適化。

```mermaid
classDiagram
    class BaseRule {
        <<abstract>>
        +need_financials() bool*
        +calculate(ticker_id, base_date) float*
        +get_prices(ticker_id, base_date, lookback_days) DataFrame
        +get_financial(ticker_id, fiscal_year) dict
        +get_latest_financial(ticker_id, base_date) dict
        +get_indicator(ticker_id, date, rule_name) float
    }

    class MomentumRule {
        +need_financials() bool : False
        +calculate(ticker_id, base_date) float
        -calc_momentum_3m(prices) float
        -calc_momentum_6m(prices) float
        -calc_momentum_12m(prices) float
    }

    class ValueRule {
        +need_financials() bool : True
        +calculate(ticker_id, base_date) float
        -score_PER(per) float
        -score_PBR(pbr) float
        -score_div_yield(dy) float
    }

    class QualityRule {
        +need_financials() bool : True
        +calculate(ticker_id, base_date) float
        -score_ROE(roe) float
        -score_equity_ratio(ratio) float
        -score_op_margin(margin) float
    }

    class SizeRule {
        +need_financials() bool : False
        +calculate(ticker_id, base_date) float
    }

    class LowVolRule {
        +need_financials() bool : False
        +calculate(ticker_id, base_date) float
        -calc_volatility(prices) float
    }

    class PeadRule {
        +need_financials() bool : False
        +calculate(ticker_id, base_date) float
        -fetch_earnings_data(symbol) dict
    }

    class SentimentRule {
        +need_financials() bool : False
        +calculate(ticker_id, base_date) float
    }

    class TextScoreRule {
        +need_financials() bool : True
        +calculate(ticker_id, base_date) float
    }

    class AnomalyRule {
        +need_financials() bool : False
        +calculate(ticker_id, base_date) float
        -calc_volume_ratio(prices) float
        -calc_volatility_ratio(prices) float
    }

    BaseRule <|-- MomentumRule
    BaseRule <|-- ValueRule
    BaseRule <|-- QualityRule
    BaseRule <|-- SizeRule
    BaseRule <|-- LowVolRule
    BaseRule <|-- PeadRule
    BaseRule <|-- SentimentRule
    BaseRule <|-- TextScoreRule
    BaseRule <|-- AnomalyRule
```

## 3b. クラス図 — モジュール構造

主要モジュール（Runner, DBSchema, Ranking, Charts, Tabs）の依存関係。

```mermaid
classDiagram
    class Runner {
        +discover_rules()
        +run_backtest()
        +compute_total_ranking()
        +save_results()
        +get_rule_names()
    }

    class DBSchema {
        +get_connection()
        +init_db()
        +log_error()
    }

    class Ranking {
        +build_ranking_data()
        +build_total_ranking_simple()
    }

    class Charts {
        +create_price_chart()
        +fetch_prices_for_chart()
    }

    class Tabs {
        +render_tab()
        +render_total_tab()
    }

    Runner ..> DBSchema : 結果保存・取得
    BaseRule ..> DBSchema : データ取得
    Tabs ..> Charts : チャート描画
    Tabs ..> Ranking : ランキング表示
```

---

## 4. マインドマップ — システム概念の階層整理

```mermaid
mindmap
  root((stockChecker))
    UI_Layer
      app.py
        メインエントリポイント
        Streamlit ページ設定
        日付選択ウィジェット
        Run Backtest ボタン
      ui/tabs.py
        render_tab: ルール別タブ
        render_total_tab: 総合タブ
        render_chart_controls
      ui/charts.py
        create_price_chart: Plotly生成
        20日移動平均線
        出来高バー
      ui/ranking.py
        build_ranking_data
        build_total_ranking_simple
    Rule_Layer
      Plugin_Engine
        rules/runner.py
          discover_rules: 動的検出
          run_backtest: 実行
          compute_total_ranking
          save_results
        rules/base.py
          BaseRule 抽象基底
      MomentumRule
        3ヶ月_6ヶ月_12ヶ月リターン
        加重平均 0.3_0.3_0.4
      ValueRule
        PER_逆数
        PBR_逆数
        配当利回り
      QualityRule
        ROE
        自己資本比率
        営業利益率
      SizeRule
        時価総額閾値判定
        小型株バイアス
      LowVolRule
        対数収益率の標準偏差
        年率換算 x sqrt252
      PeadRule
        yfinance決算サプライズ
        期待外れドリフト
      SentimentRule
        NewsAPI + Finnhub
        FinBERT 感情分析
      TextScoreRule
        テキスト分析スコア
        ROEヒューリスティック代替
      AnomalyRule
        出来高急増
        ボラティリティ急変
    Data_Layer
      DB_Schema SQLite
        tickers
        prices
        financials
        indicators
        backtest_results
        sentiment_download_log
        error_log
      db/tickers.py
        download_jpx_list: Prime_Standard_Growth
        fetch_sp500_from_wikipedia
        CURATED_US_TICKERS: 50銘柄
      db/downloader_prices.py
        download_single_price: yfinance
        download_all: 全ティッカー
        update_incremental: 差分更新
      db/downloader_financials.py
        fetch_yfinance_financials: US
        fetch_edinet_financials: 日本
        download_all
        update_accumulate
      db/downloader_sentiment.py
        fetch_news_newsapi
        fetch_news_finnhub
        analyze_sentiment: FinBERT
        download_next_batch: バッチ処理
    Configuration
      config.py
        python-dotenv 環境変数
        DB_PATH: backtest.db
        API_Keys
          NEWSAPI_KEY
          FINNHUB_API_KEY
          EDINET_API_KEY
        Parameters
          PRICE_LOOKBACK_YEARS: 10
          FINANCIAL_LOOKBACK_YEARS: 4
          SENTIMENT_BATCH_SIZE: 50
          SENTIMENT_MIN_INTERVAL_HOURS: 24
          MAX_RETRIES: 3
          RETRY_WAIT_SECONDS: 60
    External_APIs
      Yahoo_Finance yfinance
        株価履歴データ
        財務諸表
        決算サプライズ
        時価総額
      NewsAPI
        ニュース記事検索API
      Finnhub
        企業ニュース
        代替データ
      JPX_東京証券取引所
        Prime市場CSV
        Standard市場CSV
        Growth市場CSV
      Wikipedia
        S&P500構成銘柄一覧
      EDINET
        日本企業EDINET開示
      SEC_EDGAR
        US企業財務書類
      HuggingFace
        ProsusAI/finbert モデル
    Seed_Script
      seed.py
        10銘柄デモデータ
        AAPL_MSFT_GOOGL_AMZN_NVDA
        株価10年分ダウンロード
        財務データダウンロード
```

---

## 5. 状態遷移図 — データダウンロードのライフサイクル

```mermaid
stateDiagram-v2
    [*] --> PENDING

    state PENDING {
        [*] --> 待機中
    }

    PENDING --> DOWNLOADING: download_all() /<br>download_next_batch() /<br>update_incremental() 呼び出し

    state DOWNLOADING {
        [*] --> HTTP要求送信
        HTTP要求送信 --> 応答待機
    }

    DOWNLOADING --> VALIDATING: HTTP 200 OK<br>データ受信完了

    state VALIDATING {
        [*] --> 列数チェック
        列数チェック --> 型チェック
        型チェック --> 範囲チェック
    }

    VALIDATING --> SAVING: 全チェック通過

    state SAVING {
        [*] --> DB接続
        DB接続 --> トランザクション開始
        トランザクション開始 --> INSERT OR REPLACE
        INSERT OR REPLACE --> COMMIT
    }

    SAVING --> COMPLETED: COMMIT成功

    note right of COMPLETED
        sentiment: 24h クールダウン
        prices: 最終日以降のみ
        financials: 新年度のみ追記
    end note

    COMPLETED --> PENDING: クールダウン期間経過 /<br>次回バッチスケジュール

    DOWNLOADING --> FAILED: APIエラー /<br>ネットワーク障害 /<br>レート制限 /<br>タイムアウト

    VALIDATING --> FAILED: データ欠損 /<br>空DataFrame /<br>フォーマット異常

    SAVING --> FAILED: DB制約違反 /<br>一意制約 /<br>ディスク容量不足

    FAILED --> RETRY_WAITING: log_error() 記録

    state RETRY_WAITING {
        [*] --> RETRY_WAIT_SECONDS(60s) 待機
    }

    RETRY_WAITING --> DOWNLOADING: リトライ回数 &lt; MAX_RETRIES(3)<br>→ 再試行

    RETRY_WAITING --> PENDING: リトライ回数 &gt;= MAX_RETRIES(3)<br>→ 最大試行到達<br>次回スケジュール待ち

    FAILED --> PENDING: 手動リセット
```
