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
def get_connection() -> sqlite3.Connection:
    """SQLite データベース接続を取得する。

    接続には Row ファクトリ・WAL モード・外部キー制約が設定される。

    Returns:
        sqlite3.Connection: 設定済みのデータベース接続オブジェクト。

    Raises:
        sqlite3.Error: DB ファイルのオープンに失敗した場合。
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS tickers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT NOT NULL UNIQUE,
            name          TEXT,
            market        TEXT NOT NULL,
            sector        TEXT,
            market_cap    REAL,
            shares_outstanding REAL,
            is_active     INTEGER DEFAULT 1,
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tickers_market ON tickers(market);
        CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers(symbol);

        CREATE TABLE IF NOT EXISTS prices (
            ticker_id     INTEGER NOT NULL,
            date          TEXT NOT NULL,
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
        CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

        CREATE TABLE IF NOT EXISTS financials (
            ticker_id         INTEGER NOT NULL,
            fiscal_year       INTEGER NOT NULL,
            revenue           REAL,
            operating_income  REAL,
            net_income        REAL,
            total_assets      REAL,
            total_equity      REAL,
            cash_flow         REAL,
            per               REAL,
            pbr               REAL,
            roe               REAL,
            dividend_yield    REAL,
            source            TEXT DEFAULT 'yfinance',
            report_date       TEXT,
            PRIMARY KEY (ticker_id, fiscal_year),
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)
        );

        CREATE TABLE IF NOT EXISTS indicators (
            ticker_id     INTEGER NOT NULL,
            date          TEXT NOT NULL,
            rule_name     TEXT NOT NULL,
            score         REAL,
            details_json  TEXT,
            PRIMARY KEY (ticker_id, date, rule_name),
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)
        );
        CREATE INDEX IF NOT EXISTS idx_indicators_rule_date ON indicators(rule_name, date);

        CREATE TABLE IF NOT EXISTS backtest_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            base_date     TEXT NOT NULL,
            rule_name     TEXT NOT NULL,
            ticker_id     INTEGER NOT NULL,
            score         REAL,
            rank          INTEGER,
            executed_at   TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)
        );
        CREATE INDEX IF NOT EXISTS idx_backtest_base ON backtest_results(base_date, rule_name);

        CREATE TABLE IF NOT EXISTS sentiment_download_log (
            ticker_id         INTEGER PRIMARY KEY,
            last_downloaded_at TEXT,
            next_download_at   TEXT,
            articles_count     INTEGER DEFAULT 0,
            error_count        INTEGER DEFAULT 0,
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)
        );

        CREATE TABLE IF NOT EXISTS error_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT DEFAULT (datetime('now')),
            operation     TEXT,
            ticker_id     INTEGER,
            error_message TEXT,
            FOREIGN KEY (ticker_id) REFERENCES tickers(id)
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
    cursor.execute(
        "INSERT INTO error_log (operation, ticker_id, error_message) VALUES (?, ?, ?)",
        (operation, ticker_id, message),
    )
    conn.commit()
    conn.close()