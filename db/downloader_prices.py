"""株価データのダウンロード・保存

yfinance を使用して指定銘柄の日次株価を取得し、
prices テーブルへの保存・差分更新を行う。
"""

import time
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from config import PRICE_LOOKBACK_YEARS, MAX_RETRIES, RETRY_WAIT_SECONDS
from db.schema import get_connection, log_error


# MAX_RETRIES 回のリトライループ — ネットワーク一時障害で落ちても自動再試行する
def download_single_price(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """指定銘柄の株価履歴を yfinance からダウンロードする。

    リトライ処理付きで、auto_adjust=True（配当・分割調整済み）で取得する。

    Args:
        symbol: 銘柄シンボル（例: "AAPL"）。
        start: 開始日（"YYYY-MM-DD" 形式）。
        end: 終了日（"YYYY-MM-DD" 形式）。

    Returns:
        Optional[pd.DataFrame]: yfinance の履歴 DataFrame。失敗時は None。

    Raises:
        なし（例外は関数内で捕捉され、リトライ後に None を返す）。
    """
    for attempt in range(MAX_RETRIES):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, auto_adjust=True)
            if df is not None and not df.empty:
                return df
            return None
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                return None


def download_all() -> None:
    """全アクティブ銘柄の株価履歴を一括ダウンロードする。

    Returns:
        None

    注意:
        - 各銘柄間に 0.2 秒のスリープを入れ、API 負荷を軽減する。
        - ダウンロード失敗銘柄は error_log に記録される。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol FROM tickers WHERE is_active = 1")
    tickers = cursor.fetchall()
    conn.close()

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365 * PRICE_LOOKBACK_YEARS)).strftime("%Y-%m-%d")

    total = len(tickers)
    for idx, row in enumerate(tickers):
        ticker_id = row["id"]
        symbol = row["symbol"]
        print(f"[{idx+1}/{total}] Downloading prices: {symbol}")

        df = download_single_price(symbol, start_date, end_date)
        if df is None:
            log_error("download_price", ticker_id, f"No data for {symbol}")
            continue

        save_prices(ticker_id, df)
        time.sleep(0.2)

    print("Price download complete.")


# COALESCE(MAX(p.date), '1900-01-01') — 価格データが 1 件もない銘柄は '1900-01-01' を初期値とする
def update_incremental() -> None:
    """最終取得日以降の株価データを差分更新する。

    Returns:
        None

    注意:
        - 最終取得日の 5 日前から再取得し、欠損を補完する。
        - 当日のデータが既に存在する銘柄はスキップされる。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.symbol, COALESCE(MAX(p.date), '1900-01-01') as last_date
        FROM tickers t
        LEFT JOIN prices p ON t.id = p.ticker_id
        WHERE t.is_active = 1
        GROUP BY t.id, t.symbol
    """)
    tickers = cursor.fetchall()
    conn.close()

    end_date = datetime.now().strftime("%Y-%m-%d")

    for row in tickers:
        ticker_id = row["id"]
        symbol = row["symbol"]
        last_date = row["last_date"]

        if last_date >= end_date:
            continue

        start_date = (datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
        print(f"Updating: {symbol} from {start_date}")

        df = download_single_price(symbol, start_date, end_date)
        if df is not None and not df.empty:
            save_prices(ticker_id, df)

        time.sleep(0.2)

    print("Incremental update complete.")


def save_prices(ticker_id: int, df: pd.DataFrame) -> None:
    """株価 DataFrame を prices テーブルに保存する。

    Args:
        ticker_id: 銘柄 ID。
        df: yfinance 形式の株価 DataFrame（Open / High / Low / Close / Volume / Dividends / Stock Splits）。

    Returns:
        None

    Raises:
        sqlite3.Error: DB 書き込みに失敗した場合。
    """
    conn = get_connection()
    cursor = conn.cursor()

    rows = []
    for date_idx, row in df.iterrows():
        date_str = pd.Timestamp(date_idx).strftime("%Y-%m-%d")
        rows.append((
            ticker_id, date_str,
            row.get("Open"), row.get("High"),
            row.get("Low"), row.get("Close"),
            int(row.get("Volume", 0)) if pd.notna(row.get("Volume")) else 0,
            float(row.get("Dividends", 0)) if pd.notna(row.get("Dividends")) else 0.0,
            float(row.get("Stock Splits", 1)) if pd.notna(row.get("Stock Splits")) else 1.0,
        ))

    cursor.executemany("""
        INSERT OR REPLACE INTO prices
            (ticker_id, date, open, high, low, close, volume, dividends, splits)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

    conn.commit()
    conn.close()