"""銘柄一覧の取得・管理

JPX（日本取引所）・Wikipedia（S&P500）から銘柄リストを取得し、
tickers テーブルを更新する。厳選 US 銘柄の定数リストも保持する。
"""

import io
import csv
import requests
import pandas as pd
from typing import List, Tuple, Optional

from config import JPX_TICKER_URLS
from db.schema import get_connection

CURATED_US_TICKERS: List[Tuple[str, str]] = [
    ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corp."), ("GOOGL", "Alphabet Inc."),
    ("AMZN", "Amazon.com Inc."), ("NVDA", "NVIDIA Corp."), ("META", "Meta Platforms Inc."),
    ("TSLA", "Tesla Inc."), ("BRK-B", "Berkshire Hathaway"), ("JPM", "JPMorgan Chase"),
    ("V", "Visa Inc."), ("JNJ", "Johnson & Johnson"), ("WMT", "Walmart Inc."),
    ("PG", "Procter & Gamble"), ("MA", "Mastercard Inc."), ("UNH", "UnitedHealth Group"),
    ("HD", "Home Depot Inc."), ("DIS", "Walt Disney Co."), ("BAC", "Bank of America"),
    ("ADBE", "Adobe Inc."), ("NFLX", "Netflix Inc."), ("CRM", "Salesforce Inc."),
    ("KO", "Coca-Cola Co."), ("PEP", "PepsiCo Inc."), ("XOM", "Exxon Mobil Corp."),
    ("CVX", "Chevron Corp."), ("ABBV", "AbbVie Inc."), ("COST", "Costco Wholesale"),
    ("PYPL", "PayPal Holdings"), ("AMD", "Advanced Micro Devices"),
    ("INTC", "Intel Corp."), ("IBM", "IBM Corp."), ("ORCL", "Oracle Corp."),
    ("CSCO", "Cisco Systems"), ("QCOM", "Qualcomm Inc."), ("TXN", "Texas Instruments"),
    ("NFLX", "Netflix Inc."), ("CMCSA", "Comcast Corp."), ("T", "AT&T Inc."),
    ("VZ", "Verizon Communications"), ("MRK", "Merck & Co."), ("PFE", "Pfizer Inc."),
    ("TMO", "Thermo Fisher Scientific"), ("AVGO", "Broadcom Inc."),
    ("ACN", "Accenture PLC"), ("DHR", "Danaher Corp."), ("LIN", "Linde PLC"),
    ("NEE", "NextEra Energy"), ("BA", "Boeing Co."), ("GE", "General Electric"),
    ("CAT", "Caterpillar Inc."),
]


def download_jpx_list() -> List[Tuple[str, str, str]]:
    """JPX（日本取引所）から上場銘柄一覧をダウンロードする。

    プライム・スタンダード・グロースの各市場別 CSV を取得し、
    （シンボル, 銘柄名, "japan"）のタプルリストとして返す。

    Returns:
        List[Tuple[str, str, str]]: （symbol, name, market）のタプルリスト。
                                    ダウンロード失敗時は空リスト。

    Raises:
        requests.RequestException: HTTP 通信エラー（関数内で捕捉・出力済み）。
    """
    # io.StringIO(resp.text) はテキストをファイルオブジェクトのように扱う（csv.reader がファイル入力を想定しているため）
    tickers = []
    for market, url in JPX_TICKER_URLS.items():
        try:
            resp = requests.get(url, timeout=30)
            resp.encoding = "shift_jis"
            reader = csv.reader(io.StringIO(resp.text))
            header_skipped = False
            for row in reader:
                if not header_skipped:
                    header_skipped = True
                    continue
                if len(row) < 2:
                    continue
                code = row[0].strip()
                name = row[1].strip()
                symbol = f"{code}.T"
                tickers.append((symbol, name, "japan"))
        except Exception as e:
            print(f"Failed to download JPX {market}: {e}")
    return tickers


def fetch_sp500_from_wikipedia() -> List[Tuple[str, str]]:
    """Wikipedia の S&P 500 構成銘柄一覧をスクレイピングする。

    Returns:
        List[Tuple[str, str]]: （symbol, name）のタプルリスト。
                               スクレイピング失敗時は空リスト。

    注意:
        - Wikipedia のテーブル構造が変更された場合、解析に失敗する可能性がある。
    """
    # pd.read_html(url) は HTML 内の <table> を自動検出し DataFrame のリストとして返す
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        df = tables[0]
        tickers = []
        for _, row in df.iterrows():
            symbol = row["Symbol"].strip()
            name = row["Security"].strip()
            if "." in symbol:
                symbol = symbol.replace(".", "-")
            tickers.append((symbol, name))
        return tickers
    except Exception as e:
        print(f"Failed to fetch S&P 500 from Wikipedia: {e}")
        return []


# ON CONFLICT(symbol) DO UPDATE SET — SQLite の UPSERT 構文
# INSERT で UNIQUE 制約違反が発生した場合は UPDATE にフォールバックする
def update_ticker_list() -> None:
    """tickers テーブルを最新の銘柄一覧で更新する。

    S&P 500・厳選 US 銘柄・JPX 上場銘柄の全リストを取得し、
    INSERT OR ON CONFLICT でマージする（既存は updated_at 更新、
    新規は INSERT、非掲載銘柄は is_active が更新されない）。

    Returns:
        None

    Raises:
        sqlite3.Error: DB 操作に失敗した場合。
    """
    conn = get_connection()
    cursor = conn.cursor()

    total = 0

    sp500 = fetch_sp500_from_wikipedia()
    for symbol, name in sp500:
        cursor.execute("""
            INSERT INTO tickers (symbol, name, market, updated_at)
            VALUES (?, ?, 'us', datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                is_active = 1,
                updated_at = datetime('now')
        """, (symbol, name))
    total += len(sp500)
    print(f"US (S&P500) tickers: {len(sp500)}")

    for symbol, name in CURATED_US_TICKERS:
        cursor.execute("""
            INSERT INTO tickers (symbol, name, market, updated_at)
            VALUES (?, ?, 'us', datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                is_active = 1,
                updated_at = datetime('now')
        """, (symbol, name))
    total += len(CURATED_US_TICKERS)

    jp_tickers = download_jpx_list()
    for symbol, name, market in jp_tickers:
        cursor.execute("""
            INSERT INTO tickers (symbol, name, market, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                is_active = 1,
                updated_at = datetime('now')
        """, (symbol, name, market))
    total += len(jp_tickers)
    print(f"JP tickers: {len(jp_tickers)}")

    conn.commit()
    conn.close()
    print(f"Total tickers updated: {total}")


def get_all_active_tickers() -> List[dict]:
    """アクティブな全銘柄の一覧を取得する。

    Returns:
        List[dict]: 各要素が {"id": int, "symbol": str, "name": str, "market": str} のリスト。
                    シンボル順でソートされる。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, name, market FROM tickers WHERE is_active = 1 ORDER BY symbol")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_ticker_by_symbol(symbol: str) -> Optional[dict]:
    """指定されたシンボルに対応する銘柄情報を取得する。

    Args:
        symbol: 銘柄シンボル（例: "AAPL"）。

    Returns:
        Optional[dict]: {"id": int, "symbol": str, "name": str, "market": str}。
                        該当銘柄が存在しない場合は None。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, name, market FROM tickers WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None