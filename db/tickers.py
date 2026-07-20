"""銘柄一覧の取得・管理

JPX（日本取引所）・Wikipedia（S&P500）から銘柄リストを取得し、
tickers テーブルを更新する。厳選 US 銘柄の定数リストも保持する。
"""

import io
import requests
import pandas as pd
from typing import List, Tuple, Optional

from config import JPX_TICKER_URL
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

    公式Excelファイル（data_j.xls）を pd.read_excel() + xlrd で読み取り、
    プライム・スタンダード・グロースの内国株式を抽出し、
    （シンボル, 銘柄名, "japan"）のタプルリストとして返す。

    pd.read_excel() は MS Office を必要とせず、Python ライブラリ xlrd のみで動作する。

    Returns:
        List[Tuple[str, str, str]]: （symbol, name, market）のタプルリスト。
                                    ダウンロード失敗時は空リスト。

    Raises:
        requests.RequestException: HTTP 通信エラー（関数内で捕捉・出力済み）。
    """
    try:
        resp = requests.get(JPX_TICKER_URL, timeout=30)
        resp.raise_for_status()
        # io.BytesIO: ダウンロードしたバイナリをファイルのように扱う（pd.read_excel はファイル or バッファを入力とする）
        df = pd.read_excel(io.BytesIO(resp.content), engine="xlrd", header=None)
        # 1行目はヘッダー行なのでスキップ、2行目以降がデータ
        data = df.iloc[1:]
        # 3列目（index=3）= 市場・商品区分。'内国株式'（国内株式）を含む行のみ抽出
        # これにより ETF・REIT・PRO Market・外国株式などが除外される
        domestic = data[data.iloc[:, 3].str.contains("内国株式", na=False)].copy()
        tickers = []
        for _, row in domestic.iterrows():
            code = str(row.iloc[1]).strip()  # 証券コード（"1301" や "130A" など。文字列のまま保持）
            name = str(row.iloc[2]).strip()  # 銘柄名
            symbol = f"{code}.T"
            tickers.append((symbol, name, "japan"))
        return tickers
    except Exception as e:
        print(f"Failed to download JPX list: {e}")
        return []


def fetch_sp500_from_wikipedia() -> List[Tuple[str, str]]:
    """Wikipedia の S&P 500 構成銘柄一覧をスクレイピングする。

    Returns:
        List[Tuple[str, str]]: （symbol, name）のタプルリスト。
                                スクレイピング失敗時は空リスト。

    注意:
        - Wikipedia のテーブル構造が変更された場合、解析に失敗する可能性がある。
    """
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        # 明示的な User-Agent: Wikipedia は Bot アクセスを制限するため、ブラウザ風のヘッダーを設定
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        # pd.read_html(): HTML の <table> 要素を全て DataFrame のリストとしてパース
        tables = pd.read_html(io.StringIO(resp.text))
        # tables[0]: 最初のテーブル（S&P 500 構成銘柄一覧）を取得
        df = tables[0]
        tickers = []
        for _, row in df.iterrows():
            symbol = row["Symbol"].strip()
            name = row["Security"].strip()
            if "." in symbol:
                symbol = symbol.replace(".", "-")  # 例: BRK.B → BRK-B（yfinance の形式に合わせる）
            tickers.append((symbol, name))
        return tickers
    except Exception as e:
        print(f"Failed to fetch S&P 500 from Wikipedia: {e}")
        return []


# ON CONFLICT(symbol) DO UPDATE SET、excluded.xxxに注意。詳細はコメントアウトで説明している。
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

    # S&P 500 構成銘柄を tickers に upsert（market='us'）
    sp500 = fetch_sp500_from_wikipedia()
    for symbol, name in sp500:
        cursor.execute("""
            INSERT INTO tickers (symbol, name, market, updated_at)
            VALUES (?, ?, 'us', datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET       -- INSERTしてsymbolに衝突(UNIQUE 制約違反)が発生した場合は UPDATE にフォールバックする(SQLite の UPSERT 構文)
                name = excluded.name,               -- 本来 INSERT しようとした値（excludedは競合時に UPDATE 側で参照するための SQLite の特殊テーブル）
                market = excluded.market,
                is_active = 1,
                updated_at = datetime('now')
        """, (symbol, name))
    total += len(sp500)
    print(f"US (S&P500) tickers: {len(sp500)}")

    # 厳選 US 銘柄を upsert（S&P 500 と重複する場合は updated_at のみ更新）
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

    # JPX 上場銘柄を upsert（market='japan'）
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
    # is_active = 1: 有効な銘柄のみ（0 = 無効/削除扱い）
    cursor.execute("SELECT id, symbol, name, market FROM tickers WHERE is_active = 1 ORDER BY symbol")
    # dict(r): sqlite3.Row オブジェクトを通常の辞書に変換（JSON シリアライズなどに便利）
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
    # ? は SQLite のプレースホルダー。Python の変数を安全に埋め込む（SQL インジェクション防止）
    cursor.execute("SELECT id, symbol, name, market FROM tickers WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    # 該当行があれば辞書に変換、なければ None を返す
    return dict(row) if row else None