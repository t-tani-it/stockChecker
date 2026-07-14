"""財務データのダウンロード・保存

yfinance または EDINET から財務諸表データを取得し、
financials テーブルへの保存を行う。
"""

import time
import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Optional

from config import FINANCIAL_LOOKBACK_YEARS, MAX_RETRIES, RETRY_WAIT_SECONDS
from db.schema import get_connection, log_error


# yfinance の ticker.info は 1 回の API 呼び出しで多数のファンダメンタル指標を取得できる
# ticker.financials / balance_sheet / cashflow は縦軸が勘定科目、横軸が年度の DataFrame
def fetch_yfinance_financials(symbol: str) -> Optional[dict]:
    """指定銘柄の財務データを yfinance から取得する。

    info（PER・PBR・ROE・時価総額等）と financials / balance_sheet / cashflow の
    各 DataFrame をまとめて返す。

    Args:
        symbol: 銘柄シンボル（例: "AAPL"）。

    Returns:
        Optional[dict]: info と各 DataFrame を含む辞書。失敗時は None。

    Raises:
        なし（例外は関数内で捕捉され、リトライ後に None を返す）。
    """
    for attempt in range(MAX_RETRIES):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            result = {
                "per": info.get("trailingPE"),
                "pbr": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "dividend_yield": info.get("dividendYield"),
                "market_cap": info.get("marketCap"),
                "revenue": info.get("totalRevenue"),
                "operating_margin": info.get("operatingMargins"),
            }

            financials = ticker.financials
            balance_sheet = ticker.balance_sheet
            cashflow = ticker.cashflow
            earnings_dates = ticker.earnings_dates

            result["financials_df"] = financials
            result["balance_sheet_df"] = balance_sheet
            result["cashflow_df"] = cashflow
            result["earnings_dates_df"] = earnings_dates
            result["info"] = info
            result["shares_outstanding"] = info.get("sharesOutstanding")
            return result
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                return None


def extract_fiscal_year_data(raw: dict) -> list:
    """yfinance の財務 DataFrame から会計年度別のデータを抽出する。

    financials / balance_sheet / cashflow の各 DataFrame を横断し、
    各会計年度の収益・営業利益・純利益・総資産・自己資本・キャッシュフローを
    辞書リストとして整列する。

    Args:
        raw: fetch_yfinance_financials の戻り値。

    Returns:
        list: 各要素が fiscal_year / revenue / operating_income / net_income /
              total_assets / total_equity / cash_flow / per / pbr / roe /
              dividend_yield を含む辞書のリスト。

    注意:
        - financials が空の場合、PER・PBR・ROE のみの簡易レコード 1 件を返す。
    """
    records = []
    financials = raw.get("financials_df")
    balance_sheet = raw.get("balance_sheet_df")
    cashflow = raw.get("cashflow_df")
    info = raw.get("info", {})
    earnings_dates = raw.get("earnings_dates_df")

    ed_dates = None
    if earnings_dates is not None and not earnings_dates.empty:
        ed_dates = pd.DatetimeIndex(earnings_dates.index)

    if financials is None or financials.empty:
        current_year = datetime.now().year
        records.append({
            "fiscal_year": current_year - 1,
            "revenue": raw.get("revenue"),
            "operating_income": None,
            "net_income": None,
            "total_assets": None,
            "total_equity": None,
            "cash_flow": None,
            "per": raw.get("per"),
            "pbr": raw.get("pbr"),
            "roe": raw.get("roe"),
            "dividend_yield": raw.get("dividend_yield"),
            "report_date": None,
        })
        return records

    for col in financials.columns:
        try:
            year = col.year if hasattr(col, "year") else int(col)
        except (ValueError, TypeError):
            continue

        report_date = None
        if ed_dates is not None:
            fy_end = pd.Timestamp(col)
            next_fy_end = fy_end + pd.DateOffset(years=1)
            q4_dates = ed_dates[(ed_dates >= fy_end) & (ed_dates < next_fy_end)]
            if not q4_dates.empty:
                report_date = q4_dates[0].strftime("%Y-%m-%d")

        rev = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
        op_inc = financials.loc["Operating Income"] if "Operating Income" in financials.index else None
        net_inc = financials.loc["Net Income"] if "Net Income" in financials.index else None

        total_assets = None
        total_equity = None
        if balance_sheet is not None and not balance_sheet.empty:
            if "Total Assets" in balance_sheet.index:
                total_assets = balance_sheet.loc["Total Assets"].get(col)
            if "Stockholders Equity" in balance_sheet.index:
                total_equity = balance_sheet.loc["Stockholders Equity"].get(col)
            elif "Total Equity Gross Minority Interest" in balance_sheet.index:
                total_equity = balance_sheet.loc["Total Equity Gross Minority Interest"].get(col)

        cf = None
        if cashflow is not None and not cashflow.empty:
            if "Operating Cash Flow" in cashflow.index:
                cf = cashflow.loc["Operating Cash Flow"].get(col)
            elif "Free Cash Flow" in cashflow.index:
                cf = cashflow.loc["Free Cash Flow"].get(col)

        records.append({
            "fiscal_year": year,
            "revenue": float(rev.get(col)) if rev is not None and col in rev else None,
            "operating_income": float(op_inc.get(col)) if op_inc is not None and col in op_inc else None,
            "net_income": float(net_inc.get(col)) if net_inc is not None and col in net_inc else None,
            "total_assets": float(total_assets) if total_assets is not None else None,
            "total_equity": float(total_equity) if total_equity is not None else None,
            "cash_flow": float(cf) if cf is not None else None,
            "per": raw.get("per") if records else None,
            "pbr": raw.get("pbr") if records else None,
            "roe": raw.get("roe") if records else None,
            "dividend_yield": raw.get("dividend_yield") if records else None,
            "report_date": report_date,
        })

    return records


def fetch_edinet_financials(symbol: str) -> Optional[list]:
    """EDINET（日本版 EDGAR）から財務データを取得する。

    非同期クライアントを使用して EDINET から有価証券報告書を取得し、
    財務指標を計算して extract_fiscal_year_data 互換の形式で返す。

    Args:
        symbol: 銘柄シンボル（".T" サフィックス付き日本株）。

    Returns:
        Optional[list]: 財務レコードのリスト。失敗時は None。

    注意:
        - edinet パッケージがインストールされている必要がある。
        - 現在は最新年度のみのデータを返す。
    """
    try:
        from edinet import EdinetClient
        import asyncio

        edinet_code = symbol.replace(".T", "")

        async def fetch():
            async with EdinetClient() as client:
                companies = await client.search_companies(edinet_code)
                if not companies:
                    return None
                stmt = await client.get_financial_statements(
                    companies[0].edinet_code
                )
                if stmt is None:
                    return None
                metrics = client.calculate_metrics(stmt)
                return [{
                    "fiscal_year": datetime.now().year - 1,
                    "revenue": stmt.income_statement.get("売上高"),
                    "operating_income": stmt.income_statement.get("営業利益"),
                    "net_income": stmt.income_statement.get("当期純利益"),
                    "total_assets": stmt.balance_sheet.get("総資産"),
                    "total_equity": stmt.balance_sheet.get("純資産"),
                    "cash_flow": None,
                    "per": None,
                    "pbr": None,
                    "roe": metrics.get("profitability", {}).get("ROE"),
                    "dividend_yield": None,
                }]

        return asyncio.run(fetch())
    except Exception as e:
        print(f"edinet fetch failed for {symbol}: {e}")
        return None


def download_all() -> None:
    """全アクティブ銘柄の財務データを一括ダウンロードする。

    日本株は EDINET、US 株は yfinance を使用して取得する。
    DB への保存後、各銘柄間にスリープを入れて API 負荷を軽減する。

    Returns:
        None

    注意:
        - ダウンロード失敗銘柄は error_log に記録される。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, market FROM tickers WHERE is_active = 1")
    tickers = cursor.fetchall()
    conn.close()

    total = len(tickers)
    for idx, row in enumerate(tickers):
        ticker_id = row["id"]
        symbol = row["symbol"]
        market = row["market"]
        print(f"[{idx+1}/{total}] Fetching financials: {symbol}")

        records = None
        if market == "japan":
            records = fetch_edinet_financials(symbol)

        if records is None:
            raw = fetch_yfinance_financials(symbol)
            if raw is not None:
                records = extract_fiscal_year_data(raw)
                shares = raw.get("shares_outstanding")
                if shares is not None and shares > 0:
                    conn2 = get_connection()
                    conn2.execute(
                        "UPDATE tickers SET shares_outstanding = ?, updated_at = datetime('now') WHERE id = ?",
                        (shares, ticker_id),
                    )
                    conn2.commit()
                    conn2.close()

        if records:
            save_financials(ticker_id, records)
        else:
            log_error("download_financials", ticker_id, f"No financial data for {symbol}")

        time.sleep(0.3 if market == "us" else 0.5)

    print("Financial data download complete.")


def update_accumulate() -> None:
    """財務データの一括更新（download_all のラッパー）。

    download_all() を呼び出し、全アクティブ銘柄の財務データを再取得する。
    """
    download_all()


def save_financials(ticker_id: int, records: list) -> None:
    """財務レコードのリストを financials テーブルに保存する。

    Args:
        ticker_id: 銘柄 ID。
        records: extract_fiscal_year_data 互換の辞書リスト。

    Returns:
        None

    Raises:
        sqlite3.Error: DB 書き込みに失敗した場合。
    """
    conn = get_connection()
    cursor = conn.cursor()

    for rec in records:
        cursor.execute("""
            INSERT OR IGNORE INTO financials
                (ticker_id, fiscal_year, revenue, operating_income, net_income,
                 total_assets, total_equity, cash_flow, per, pbr, roe, dividend_yield, report_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker_id, rec["fiscal_year"],
            rec["revenue"], rec["operating_income"], rec["net_income"],
            rec["total_assets"], rec["total_equity"], rec["cash_flow"],
            rec["per"], rec["pbr"], rec["roe"], rec["dividend_yield"],
            rec.get("report_date"),
        ))

    conn.commit()
    conn.close()