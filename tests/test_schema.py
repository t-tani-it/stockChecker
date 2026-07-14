"""DBスキーマのテスト

テーブル作成・Ticker CRUD・価格データのUPSERTを検証する。
"""

import os
import pytest
import tempfile

from db.schema import init_db, get_connection


# @pytest.fixture はテストの「準備→実行→後片付け」を定義するデコレータ
# autouse=True で全テストに自動適用（各テスト関数が個別に呼び出す必要なし）
# monkeypatch.setattr で config.DB_PATH を一時ファイルに差し替え（テスト間の DB 分離）
# yield の前 = 準備（setup）、後 = 後片付け（teardown）。os.unlink で一時ファイル削除
@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    """テスト用の一時データベースを作成するフィクスチャ。

    config.DB_PATH を一時ファイルに差し替え、テスト後に自動削除する。

    Yields:
        None
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    monkeypatch.setattr("config.DB_PATH", db_path)
    yield
    os.unlink(db_path)


def test_init_db_creates_tables():
    """init_db() が全テーブルを作成することを検証する。"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cursor.fetchall()}
    conn.close()

    expected = {
        "tickers", "prices", "financials", "indicators",
        "backtest_results", "sentiment_download_log", "error_log",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_ticker_insert():
    """tickers テーブルへの INSERT および SELECT を検証する。"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tickers (symbol, name, market) VALUES (?, ?, ?)",
        ("AAPL", "Apple Inc.", "us"),
    )
    conn.commit()

    cursor.execute("SELECT * FROM tickers WHERE symbol = 'AAPL'")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["name"] == "Apple Inc."
    assert row["market"] == "us"


def test_prices_insert_and_duplicate():
    """prices テーブルの INSERT および INSERT OR REPLACE（UPSERT）を検証する。"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickers (symbol, name, market) VALUES (?, ?, ?)", ("MSFT", "Microsoft", "us"))
    conn.commit()

    cursor.execute("INSERT INTO prices (ticker_id, date, close, volume) VALUES (?, ?, ?, ?)",
                   (1, "2024-01-05", 150.0, 1000000))
    conn.commit()

    cursor.execute("INSERT OR REPLACE INTO prices (ticker_id, date, close, volume) VALUES (?, ?, ?, ?)",
                   (1, "2024-01-05", 155.0, 2000000))
    conn.commit()

    cursor.execute("SELECT close, volume FROM prices WHERE ticker_id = 1 AND date = '2024-01-05'")
    row = cursor.fetchone()
    conn.close()

    assert row["close"] == 155.0
    assert row["volume"] == 2000000


def test_log_error():
    """log_error() が error_log テーブルにレコードを作成することを検証する。"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickers (symbol, name, market) VALUES (?, ?, ?)", ("TEST", "Test Inc.", "us"))
    conn.commit()
    conn.close()

    from db.schema import log_error
    log_error("test_operation", 1, "test error message")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM error_log WHERE operation = 'test_operation'")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["error_message"] == "test error message"