# DATA_MODEL.md - データモデル

## データベース: SQLite (backtest.db)

## テーブル一覧

### 1. tickers - 銘柄マスタ
```sql
CREATE TABLE tickers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL UNIQUE,      -- 7203.T / AAPL
    name          TEXT,                       -- 企業名
    market        TEXT NOT NULL,              -- 'japan' / 'us'
    sector        TEXT,                       -- セクター
    is_active     INTEGER DEFAULT 1,         -- 上場中なら1
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_tickers_market ON tickers(market);
CREATE INDEX idx_tickers_symbol ON tickers(symbol);
```

### 2. prices - 日次株価
```sql
CREATE TABLE prices (
    ticker_id     INTEGER NOT NULL,
    date          TEXT NOT NULL,              -- YYYY-MM-DD
    open          REAL,
    high          REAL,
    low           REAL,
    close         REAL,
    volume        INTEGER,
    dividends     REAL DEFAULT 0,
    splits        REAL DEFAULT 1,
    PRIMARY KEY (ticker_id, date),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
);
CREATE INDEX idx_prices_date ON prices(date);
```

### 3. financials - 財務データ（年次、蓄積）
```sql
CREATE TABLE financials (
    ticker_id         INTEGER NOT NULL,
    fiscal_year       INTEGER NOT NULL,       -- 2020, 2021, ...
    revenue           REAL,                   -- 売上高
    operating_income  REAL,                   -- 営業利益
    net_income        REAL,                   -- 当期純利益
    total_assets      REAL,                   -- 総資産
    total_equity      REAL,                   -- 自己資本
    cash_flow         REAL,                   -- 営業CF
    per               REAL,                   -- PER
    pbr               REAL,                   -- PBR
    roe               REAL,                   -- ROE
    dividend_yield    REAL,                   -- 配当利回り
    source            TEXT DEFAULT 'yfinance', -- 'yfinance'/'edinet'/'sec-edgar'
    PRIMARY KEY (ticker_id, fiscal_year),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
);
```

### 4. indicators - 計算済み指標（ルールごと）
```sql
CREATE TABLE indicators (
    ticker_id     INTEGER NOT NULL,
    date          TEXT NOT NULL,              -- YYYY-MM-DD
    rule_name     TEXT NOT NULL,              -- 'momentum'/'value'/...
    score         REAL,                       -- 0-100
    details_json  TEXT,                       -- 計算詳細（任意JSON）
    PRIMARY KEY (ticker_id, date, rule_name),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
);
CREATE INDEX idx_indicators_rule_date ON indicators(rule_name, date);
```

### 5. backtest_results - バックテスト結果
```sql
CREATE TABLE backtest_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    base_date     TEXT NOT NULL,              -- 基準日
    rule_name     TEXT NOT NULL,              -- ルール名（'total' は総合）
    ticker_id     INTEGER NOT NULL,
    score         REAL,
    rank          INTEGER,
    executed_at   TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
);
CREATE INDEX idx_backtest_base ON backtest_results(base_date, rule_name);
```

### 6. sentiment_download_log - センチメントDL管理
```sql
CREATE TABLE sentiment_download_log (
    ticker_id         INTEGER PRIMARY KEY,
    last_downloaded_at TEXT,                  -- 最終DL日時
    next_download_at   TEXT,                  -- 次回DL予定日時
    articles_count     INTEGER DEFAULT 0,     -- DL済み記事数
    error_count        INTEGER DEFAULT 0,     -- エラー回数
    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
);
```

### 7. error_log - エラーログ
```sql
CREATE TABLE error_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT DEFAULT (datetime('now')),
    operation     TEXT,                       -- 'download_price'/'sentiment'/...
    ticker_id     INTEGER,
    error_message TEXT,
    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
);
```

## データ蓄積の成長イメージ

| 運用年数 | prices行数(概算) | financials行数(概算) |
|----------|-----------------|---------------------|
| 初年度   | 3,000万行 (12k×250日×10年) | 4.8万行 (12k×4年) |
| 2年目    | 3,300万行 (+差分250日分) | 6.0万行 (+1年分 12k) |
| 5年目    | 4,200万行 | 9.6万行 (12k×8年) |

※ pricesは初回10年DL後は差分のみ増加
※ financialsは年々確実に蓄積される
