"""全銘柄のデータを一括ダウンロード（seed.py とは独立したフルバージョン）

market を指定してダウンロード対象市場を絞り込める。
データ種別は --price / --financials / --pead / --sentiment で選択可能（未指定=全種別）。

使い方:
    python download_full.py                      # 全market × 全データ種別
    python download_full.py us                   # US株のみ × 全データ種別
    python download_full.py japan --price        # 日本株の株価のみ
    python download_full.py japan --pead         # 日本株のPEADのみ
    python download_full.py all --sentiment      # 全marketのセンチメントのみ
    python download_full.py us --price --pead    # US株の株価 + PEADのみ
"""

import argparse
import time
import sys
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from db.schema import init_db, get_connection, log_error
from db.tickers import update_ticker_list
from db.downloader_prices import download_single_price, save_prices, update_incremental as update_prices_incremental
from db.downloader_financials import (
    fetch_yfinance_financials,
    extract_fiscal_year_data,
    save_financials,
    _load_prices_df,
    update_incremental as update_financials_incremental,
)
from db.downloader_sentiment import download_next_batch
from rules.pead import PeadRule
from config import PRICE_LOOKBACK_YEARS, SENTIMENT_BATCH_SIZE


def get_tickers_by_market(market: str):
    """指定された市場のアクティブな全銘柄を (id, symbol) のリストで取得する。

    Args:
        market: "us" / "japan" / "all"（全market）。

    Returns:
        list[sqlite3.Row]: {"id": int, "symbol": str} 形式の行リスト。
    """
    conn = get_connection()
    cursor = conn.cursor()
    if market == "all":
        cursor.execute(
            "SELECT id, symbol FROM tickers WHERE is_active = 1"
        )
    else:
        cursor.execute(
            "SELECT id, symbol FROM tickers WHERE market = ? AND is_active = 1",
            (market,),
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def _market_label(market: str) -> str:
    return {"us": "US", "japan": "Japan", "all": "ALL"}.get(market, market.upper())


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
                prices_df = _load_prices_df(ticker_id)
                records = extract_fiscal_year_data(raw, prices_df)
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


def update_pead_incremental(tickers):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT ticker_id FROM indicators
        WHERE rule_name = 'PEAD'
          AND strftime('%Y', date) = strftime('%Y', 'now')
    """)
    already_done = set(row["ticker_id"] for row in cursor.fetchall())
    conn.close()

    remaining = [t for t in tickers if t["id"] not in already_done]

    total = len(remaining)
    ok = 0
    ng = 0
    rule = PeadRule()
    for idx, row in enumerate(remaining):
        ticker_id = row["id"]
        symbol = row["symbol"]
        print(f"[{idx+1}/{total}] PEAD (incremental): {symbol}")
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

    print(f"PEAD incremental done: ok={ok}, ng={ng}")
    return ok > 0


def main():
    parser = argparse.ArgumentParser(
        description="全銘柄データ一括ダウンロード（market / データ種別を選択可能）"
    )
    parser.add_argument(
        "market", nargs="?", default="all",
        choices=["us", "japan", "all"],
        help="対象市場: us / japan / all (default: all)",
    )
    parser.add_argument("--price", action="store_true", help="株価をダウンロード")
    parser.add_argument("--financials", action="store_true", help="財務データをダウンロード")
    parser.add_argument("--pead", action="store_true", help="PEAD（決算サプライズ）を計算")
    parser.add_argument("--sentiment", action="store_true", help="センチメント（ニュース感情分析）を実行")
    parser.add_argument("--incremental", "--inc", action="store_true", help="差分更新モード（各データ種別の未取得分のみ処理）")
    args = parser.parse_args()

    flags = [args.price, args.financials, args.pead, args.sentiment]
    run_all = not any(flags)

    # --incremental 単独指定は price 差分更新のみ実行
    if args.incremental and not any(flags):
        args.price = True
    market_label = _market_label(args.market)

    if run_all:
        print(f"\n=== 全データダウンロード: market={market_label} ===")
    else:
        selected = [name for name, f in
                     [("price", args.price), ("financials", args.financials),
                      ("pead", args.pead), ("sentiment", args.sentiment)]
                     if f]
        print(f"\n=== データダウンロード: market={market_label}, 種別={selected} ===")

    # --- Step 1: DB初期化 ---
    if run_all or args.price or args.financials:
        print("\n--- Step 1: Initialize database ---")
        init_db()
        print("DB initialized.")

    # --- Step 2: 銘柄リスト更新 ---
    if run_all or args.price or args.financials or args.pead:
        print("\n--- Step 2: Update ticker list ---")
        update_ticker_list()
    else:
        print("\n--- Step 2: Skip ticker update (sentiment only) ---")

    # --- Step 3: 対象銘柄取得 ---
    tickers = get_tickers_by_market(args.market)
    print(f"\nTarget tickers: {len(tickers)} ({market_label})")

    # --- Step 4: 各データ種別を実行 ---
    if run_all or args.price:
        if args.incremental:
            print("\n--- Prices (incremental) ---")
            market_param = None if args.market == "all" else args.market
            update_prices_incremental(market=market_param)
        else:
            print("\n--- Prices ---")
            download_prices_all(tickers)

    if run_all or args.financials:
        if args.incremental:
            print("\n--- Financials (incremental) ---")
            market_param = None if args.market == "all" else args.market
            update_financials_incremental(market=market_param)
        else:
            print("\n--- Financials ---")
            download_financials_all(tickers)

    if run_all or args.pead:
        if args.incremental:
            print("\n--- PEAD (incremental) ---")
            update_pead_incremental(tickers)
        else:
            print("\n--- PEAD pre-computation ---")
            download_pead_all(tickers)

    if run_all or args.sentiment:
        market_param = None if args.market == "all" else args.market
        if args.incremental:
            print(f"\n--- Sentiment (incremental, market={market_param or 'all'}) ---")
        else:
            print(f"\n--- Sentiment (market={market_param or 'all'}) ---")
        try:
            download_next_batch(n=SENTIMENT_BATCH_SIZE, market=market_param, incremental=args.incremental)
        except Exception as e:
            print(f"Sentiment skipped or failed: {e}")

    print("\nAll done!")


if __name__ == "__main__":
    main()
