"""stockChecker 初期データ投入スクリプト

指定された10銘柄（AAPL, MSFT 等）の株価・財務データ・センチメントを
yfinance / NewsAPI / Finnhub からダウンロードし、
すぐにバックテストを実行できる状態にデータベースを初期化する。

使用例:
    python seed.py
"""

import time
import yfinance as yf
from db.schema import init_db, get_connection
from db.tickers import update_ticker_list
from db.downloader_prices import download_single_price, save_prices
from db.downloader_financials import fetch_yfinance_financials, extract_fiscal_year_data, save_financials

# すぐにバックテストを試すための厳選 10 銘柄
DEMO_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "KO"]


def seed():
    """デモ用の 10 銘柄データをダウンロードし、データベースに保存する。

    銘柄ごとに時価総額・株価（10年分）・財務データ・センチメントを順次取得し、
    データベースの tickers / prices / financials / indicators テーブルへ保存する。

    Args:
        なし

    Returns:
        None

    Raises:
        KeyboardInterrupt: Ctrl+C による中断。
        その他の例外は個別にキャッチされ、警告メッセージが表示される。

    注意:
        - 各銘柄間に 0.5 秒のスリープを入れ、API 負荷を軽減する。
        - すでに存在する銘柄はスキップされず、時価総額のみ更新される。
    """
    print("=== Initializing database ===")
    init_db()

    print("\n=== Updating ticker list ===")
    update_ticker_list()

    print("\n=== Seeding demo data (10 US stocks) ===")
    conn = get_connection()
    cursor = conn.cursor()

    # DEMO_SYMBOLS の各銘柄について、時価総額・株価・財務データを順に取得する
    for symbol in DEMO_SYMBOLS:
        # ? は SQL インジェクション対策のプレースホルダ。タプル (symbol,) で値をバインドする
        cursor.execute("SELECT id FROM tickers WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                "INSERT INTO tickers (symbol, name, market) VALUES (?, ?, 'us')",
                (symbol, symbol),
            )
            conn.commit()
            ticker_id = cursor.lastrowid
        else:
            ticker_id = row["id"]

        print(f"\n[{symbol}] Fetching market cap...")
        # yf.Ticker は yfinance ライブラリの中心クラス。銘柄シンボルを渡して株価・財務情報を取得する
        try:
            tk = yf.Ticker(symbol)
            info = tk.info
            mcap = info.get("marketCap")
            if mcap:
                cursor.execute("UPDATE tickers SET market_cap = ?, updated_at = datetime('now') WHERE id = ?",
                               (mcap, ticker_id))
                conn.commit()
                print(f"  -> market_cap={mcap}")
        except Exception as e:
            print(f"  -> could not fetch market cap: {e}")

        print(f"[{symbol}] Downloading prices (10 years)...")
        df = download_single_price(symbol, "2015-01-01", "2026-07-09")
        if df is not None and not df.empty:
            save_prices(ticker_id, df)
            print(f"  -> {len(df)} price rows saved")
        else:
            print("  -> No price data")

        print(f"[{symbol}] Downloading financials...")
        raw = fetch_yfinance_financials(symbol)
        if raw is not None:
            records = extract_fiscal_year_data(raw)
            if records:
                save_financials(ticker_id, records)
                print(f"  -> {len(records)} fiscal years saved")
        else:
            print("  -> No financial data")

        # 連続リクエストで API 制限にかからないよう、銘柄間に 0.5 秒のインターバルを入れる
        time.sleep(0.5)

    conn.close()

    print("\n=== Downloading sentiment data ===")
    try:
        from db.downloader_sentiment import download_next_batch
        download_next_batch(n=50)
    except ImportError:
        print("  -> FinBERT / transformers not installed, skipping sentiment")
    except Exception as e:
        print(f"  -> Sentiment download skipped: {e}")

    print("\n=== Seed complete! ===")
    print("Run: streamlit run app.py")
    print("Then click 'バックテスト実行' to see results.")


if __name__ == "__main__":
    seed()