"""データベーススキーマ定義と接続管理

データベースの初期化（テーブル作成・インデックス作成）および
接続取得・エラーログ記録の共通関数を提供する。

テーブル一覧:
    - tickers: 銘柄マスタ
    - prices: 日次株価データ
    - financials: 財務データ
    - indicators: ルール別指標スコア
    - backtest_results: バックテスト実行結果
    - sentiment_download_log: センチメント取得ログ
    - error_log: エラーログ
"""

import sqlite3
from typing import Optional
import config


# sqlite3.Row を行ファクトリに設定すると、カラム名で値にアクセスできる辞書ライクな行オブジェクトが返る
# PRAGMA 設定: WAL モード（読み取り中でも書込可能）+ 外部キー制約 ON（デフォルト OFF）
# get_connection() は上記3行（row_factory + PRAGMA x 2）を毎回書かずに済むラッパー関数
# 直接 sqlite3.connect() を書くのと処理内容は同じ
def get_connection() -> sqlite3.Connection:
    """SQLite データベース接続を取得する。

    接続には Row ファクトリ・WAL モード・外部キー制約が設定される。

    Returns:
        sqlite3.Connection: 設定済みのデータベース接続オブジェクト。

    Raises:
        sqlite3.Error: DB ファイルのオープンに失敗した場合。
    """
    conn = sqlite3.connect(config.DB_PATH)
    # sqlite3.Row: クエリ結果の各行を「カラム名でも・インデックス番号でも」アクセスできる辞書ライクなオブジェクトにする
    # 通常のタプルだと row[0] しか使えないが、Row なら row["symbol"] も row[0] も使える
    conn.row_factory = sqlite3.Row
    # WALモード: 読み取り中でも書き込みが可能になる（デフォルトは DELETE モードで読み取り中は書込不可）
    conn.execute("PRAGMA journal_mode=WAL")
    # 外部キー制約 ON: SQLite はデフォルトで外部キー制約が無効。明示的に有効化しないと FOREIGN KEY が機能しない
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# executescript() は複数の SQL 文を ; 区切りで一括実行できる（execute は 1 文のみ）
def init_db() -> None:
    """データベースを初期化し、全テーブル・インデックスを作成する。

    既存のテーブルが存在する場合は CREATE IF NOT EXISTS によりスキップされ、
    データは保持される。

    Args:
        なし

    Returns:
        None

    Raises:
        sqlite3.Error: テーブル作成に失敗した場合。
    """
    conn = get_connection()
    cursor = conn.cursor()

    # SQLite の値の型は5種類だけ: INTEGER（整数）, REAL（浮動小数）, TEXT（文字列）, BLOB（バイナリ）, NULL
    # 日時は TEXT として ISO 形式文字列で保存（SQLite に日付型は存在しない）
    # INTEGER を真偽値として使う慣習: 1=真, 0=偽
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS tickers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自動採番される一意ID（新規挿入時に最大値+1）
            symbol        TEXT NOT NULL UNIQUE,                -- 銘柄コード（例: "AAPL"）。重複不可
            name          TEXT,                                -- 会社名（NULL可）
            market        TEXT NOT NULL,                       -- 市場区分（例: "us", "japan"）。必須
            sector        TEXT,                                -- セクター情報（NULL可）
            market_cap    REAL,                                -- 時価総額（ドル）。浮動小数点
            shares_outstanding REAL,                           -- 発行済株式数
            is_active     INTEGER DEFAULT 1,                   -- 有効フラグ（1=有効, 0=無効）
            created_at    TEXT DEFAULT (datetime('now')),      -- 作成日時（自動設定）
            updated_at    TEXT DEFAULT (datetime('now'))       -- 更新日時（ただし SQLite は自動更新しないためアプリ側で明示設定が必要）
        );
        CREATE INDEX IF NOT EXISTS idx_tickers_market ON tickers(market);
        CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers(symbol);

        CREATE TABLE IF NOT EXISTS prices (
            ticker_id     INTEGER NOT NULL,         -- 銘柄ID（tickers.id を参照）
            date          TEXT NOT NULL,             -- 日付（ISO形式）
            open          REAL,                      -- 始値（調整後）
            high          REAL,                      -- 高値（調整後）
            low           REAL,                      -- 安値（調整後）
            close         REAL,                      -- 終値（調整後）
            volume        INTEGER,                   -- 出来高
            dividends     REAL DEFAULT 0,            -- 配当金
            splits        REAL DEFAULT 1,            -- 株式分割比率
            PRIMARY KEY (ticker_id, date),         -- 複合主キー: 同じ銘柄の同じ日付のデータは重複不可
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)  -- 外部キー: tickers に存在しない ticker_id は prices に入れない
        );
        CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);  -- 日付での検索を高速化

        CREATE TABLE IF NOT EXISTS financials (
            ticker_id         INTEGER NOT NULL,         -- 銘柄ID
            fiscal_year       INTEGER NOT NULL,         -- 会計年度
            revenue           REAL,                      -- 売上高
            operating_income  REAL,                      -- 営業利益
            net_income        REAL,                      -- 当期純利益
            total_assets      REAL,                      -- 総資産
            total_equity      REAL,                      -- 自己資本
            cash_flow         REAL,                      -- 営業キャッシュフロー
            per               REAL,                      -- PER（株価収益率）
            pbr               REAL,                      -- PBR（株価純資産倍率）
            roe               REAL,                      -- ROE（自己資本利益率）
            dividend_yield    REAL,                      -- 配当利回り
            source            TEXT DEFAULT 'yfinance',   -- データ取得元（例: yfinance）
            report_date       TEXT,                      -- 決算発表日
            PRIMARY KEY (ticker_id, fiscal_year),        -- 複合主キー: 同じ銘柄の同じ年度は1行のみ
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)  -- tickers に存在する銘柄のみ
        );

        CREATE TABLE IF NOT EXISTS indicators (
            ticker_id     INTEGER NOT NULL,         -- 銘柄ID
            date          TEXT NOT NULL,             -- 評価基準日
            rule_name     TEXT NOT NULL,             -- ルール名（例: sentiment, モメンタム）
            score         REAL,                      -- スコア（0〜100 など）
            details_json  TEXT,                      -- 内訳データ（JSON文字列）
            PRIMARY KEY (ticker_id, date, rule_name),  -- 複合主キー: 銘柄×日付×ルールで一意
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)  -- tickers に存在する銘柄のみ
        );
        -- ルール名＋日付での検索を高速化（例: 特定ルールの全銘柄スコアを日付範囲で取得）
        CREATE INDEX IF NOT EXISTS idx_indicators_rule_date ON indicators(rule_name, date);

        CREATE TABLE IF NOT EXISTS backtest_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自動採番ID
            base_date     TEXT NOT NULL,             -- バックテスト基準日
            rule_name     TEXT NOT NULL,             -- 適用ルール名
            ticker_id     INTEGER NOT NULL,          -- 銘柄ID
            score         REAL,                      -- 評価スコア
            rank          INTEGER,                   -- スコア順位
            executed_at   TEXT DEFAULT (datetime('now')),  -- 実行日時（自動設定）
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)  -- tickers に存在する銘柄のみ
        );
        -- 基準日＋ルール名での検索を高速化（例: 特定日の特定ルールのランキング取得）
        CREATE INDEX IF NOT EXISTS idx_backtest_base ON backtest_results(base_date, rule_name);

        CREATE TABLE IF NOT EXISTS sentiment_download_log (
            ticker_id         INTEGER PRIMARY KEY,  -- 銘柄ID（主キー＝1銘柄につき1行のみ）
            last_downloaded_at TEXT,                 -- 最終ダウンロード日時
            next_download_at   TEXT,                 -- 次回ダウンロード予定日時
            articles_count     INTEGER DEFAULT 0,    -- ダウンロード記事数
            error_count        INTEGER DEFAULT 0,    -- エラー発生回数
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)  -- tickers に存在する銘柄のみ
        );

        CREATE TABLE IF NOT EXISTS error_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自動採番ID
            timestamp     TEXT DEFAULT (datetime('now')),      -- エラー発生日時（未指定時は自動設定）
            operation     TEXT,              -- エラーが発生した操作名（例: "download_price"）
            ticker_id     INTEGER,           -- 関連する銘柄ID（該当なしの場合はNULL）
            error_message TEXT,              -- エラーメッセージ
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)  -- tickers に存在する銘柄のみ
        );
    """)

    # 既存DBのマイグレーション: カラム追加（ALTER TABLE は IF NOT EXISTS 非対応のため個別実行）
    try:
        cursor.execute("ALTER TABLE tickers ADD COLUMN shares_outstanding REAL")
    except Exception:
        pass  # すでに存在する場合はスキップ
    try:
        cursor.execute("ALTER TABLE financials ADD COLUMN report_date TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()


def log_error(operation: str, ticker_id: Optional[int], message: str) -> None:
    """エラーログを error_log テーブルに記録する。

    Args:
        operation: エラーが発生した操作名（例: "download_price"）。
        ticker_id: 関連する銘柄 ID（関連がない場合は None）。
        message: エラーメッセージ。

    Returns:
        None

    Raises:
        sqlite3.Error: ログの書き込みに失敗した場合。
    """
    conn = get_connection()
    cursor = conn.cursor()
    # INSERT で指定した3カラムのみ。id（AUTOINCREMENT）と timestamp（DEFAULT datetime('now')）は自動入力される
    cursor.execute(
        "INSERT INTO error_log (operation, ticker_id, error_message) VALUES (?, ?, ?)",
        (operation, ticker_id, message),
    )
    conn.commit()
    conn.close()