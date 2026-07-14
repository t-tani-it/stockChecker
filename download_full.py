"""S&P 500 全銘柄のデータを一括ダウンロード（seed.py とは独立したフルバージョン）

使い方:
    python download_full.py                    # 株価 + 財務 + センチメント(50件)
    python download_full.py --sentiment        # センチメントのみ追加実行
"""

import argparse
import time
import sys
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from db.schema import init_db, get_connection, log_error
from db.tickers import update_ticker_list
from db.downloader_prices import download_single_price, save_prices
from db.downloader_financials import (
    fetch_yfinance_financials,
    extract_fiscal_year_data,
    save_financials,
)
from db.downloader_sentiment import download_next_batch
from rules.pead import PeadRule
from config import PRICE_LOOKBACK_YEARS, SENTIMENT_BATCH_SIZE


def get_us_tickers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, symbol FROM tickers WHERE market = 'us' AND is_active = 1"
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def download_prices_all(tickers):
    total = len(tickers)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365 * PRICE_LOOKBACK_YEARS)).strftime("%Y-%m-%d")

    ok = 0
    ng = 0
    for idx, row in enumerate(tickers):
        ticker_id = row["id"]
        symbol = row["symbol"]
        print(f"[{idx+1}/{total}] Downloading prices: {symbol}")
        try:
            df = download_single_price(symbol, start_date, end_date)
            if df is not None:
                save_prices(ticker_id, df)
                ok += 1
            else:
                log_error("download_price", ticker_id, f"No data for {symbol}")
                ng += 1
        except Exception as e:
            log_error("download_price", ticker_id, f"Error: {e}")
            ng += 1
        time.sleep(0.2)

    print(f"Prices done: ok={ok}, ng={ng}")


def download_financials_all(tickers):
    total = len(tickers)
    ok = 0
    ng = 0
    for idx, row in enumerate(tickers):
        ticker_id = row["id"]
        symbol = row["symbol"]
        print(f"[{idx+1}/{total}] Fetching financials: {symbol}")
        try:
            raw = fetch_yfinance_financials(symbol)
            if raw is not None:
                records = extract_fiscal_year_data(raw)
                if records:
                    save_financials(ticker_id, records)
                shares = raw.get("shares_outstanding")
                if shares is not None and shares > 0:
                    conn2 = get_connection()
                    conn2.execute(
                        "UPDATE tickers SET shares_outstanding = ?, updated_at = datetime('now') WHERE id = ?",
                        (shares, ticker_id),
                    )
                    conn2.commit()
                    conn2.close()
                ok += 1
            else:
                log_error("download_financials", ticker_id, f"No financial data for {symbol}")
                ng += 1
        except Exception as e:
            log_error("download_financials", ticker_id, f"Error: {e}")
            ng += 1
        time.sleep(0.3)

    print(f"Financials done: ok={ok}, ng={ng}")


def download_pead_all(tickers):
    total = len(tickers)
    ok = 0
    ng = 0
    rule = PeadRule()
    for idx, row in enumerate(tickers):
        ticker_id = row["id"]
        symbol = row["symbol"]
        print(f"[{idx+1}/{total}] PEAD: {symbol}")
        try:
            ticker = yf.Ticker(symbol)
            earnings = ticker.earnings_dates
            if earnings is not None and not earnings.empty:
                earnings = earnings.reset_index()
                earnings["Earnings Date"] = pd.to_datetime(earnings["Earnings Date"])
                earnings = earnings.sort_values("Earnings Date", ascending=False)
                surprise_val = None
                earnings_date = None
                for _, erow in earnings.iterrows():
                    if "Surprise(%)" in erow.index:
                        s = erow.get("Surprise(%)", None)
                        if s is not None and not pd.isna(s):
                            surprise_val = float(s)
                            earnings_date = erow["Earnings Date"].strftime("%Y-%m-%d")
                            break
                if surprise_val is not None and earnings_date is not None:
                    score = rule._surprise_to_score(surprise_val)
                    conn3 = get_connection()
                    conn3.execute(
                        "INSERT OR REPLACE INTO indicators (ticker_id, date, rule_name, score) VALUES (?, ?, 'PEAD', ?)",
                        (ticker_id, earnings_date, score),
                    )
                    conn3.commit()
                    conn3.close()
                    ok += 1
                else:
                    ng += 1
            else:
                ng += 1
        except Exception as e:
            ng += 1
        time.sleep(0.3)

    print(f"PEAD done: ok={ok}, ng={ng}")
    return ok > 0


def main():
    parser = argparse.ArgumentParser(description="S&P 500 全銘柄データダウンロード")
    parser.add_argument("--sentiment", action="store_true", help="センチメントのみ実行")
    parser.add_argument("--pead", action="store_true", help="PEAD のみ実行")
    args = parser.parse_args()

    if args.sentiment:
        print("\n--- Sentiment (US only) ---")
        try:
            download_next_batch(n=SENTIMENT_BATCH_SIZE, market="us")
        except Exception as e:
            print(f"Sentiment skipped or failed: {e}")
        print("\nAll done!")
        return

    if args.pead:
        print("\n=== PEAD pre-computation ===")
        tickers = get_us_tickers()
        print(f"Target tickers: {len(tickers)} US stocks")
        download_pead_all(tickers)
        print("\nAll done!")
        return

    print("=== Step 1/3: Initialize database ===")
    init_db()

    print("\n=== Step 2/3: Update ticker list ===")
    update_ticker_list()

    print("\n=== Step 3/3: Download data for US tickers ===")
    tickers = get_us_tickers()
    print(f"Target tickers: {len(tickers)} US stocks")

    print("\n--- Prices ---")
    download_prices_all(tickers)

    print("\n--- Financials ---")
    download_financials_all(tickers)

    print("\n--- PEAD pre-computation ---")
    download_pead_all(tickers)

    print("\n--- Sentiment (US only) ---")
    try:
        download_next_batch(n=SENTIMENT_BATCH_SIZE, market="us")
    except Exception as e:
        print(f"Sentiment skipped or failed: {e}")

    print("\nAll done!")


if __name__ == "__main__":
    main()
