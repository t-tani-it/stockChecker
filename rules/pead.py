import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from rules.base import BaseRule
from db.schema import get_connection


class PeadRule(BaseRule):
    name = "PEAD"
    description = "良い決算を出した企業は、発表後数週間〜数ヶ月上昇しやすい"

    def need_financials(self) -> bool:
        return False

    def _surprise_to_score(self, eps_pct: float) -> float:
        if eps_pct > 10:
            return 85.0
        elif eps_pct > 5:
            return 70.0
        elif eps_pct > 0:
            return 55.0
        elif eps_pct > -5:
            return 40.0
        else:
            return 20.0

    def _fetch_earnings(self, symbol: str):
        ticker = yf.Ticker(symbol)
        return ticker.earnings_dates

    def calculate(self, ticker_id: int, base_date: str) -> float:
        indicator_score = self.get_indicator(ticker_id, base_date, "PEAD")
        if indicator_score is not None:
            return indicator_score

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM tickers WHERE id = ?", (ticker_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return 40.0

        symbol = row["symbol"]

        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(self._fetch_earnings, symbol)
                earnings = future.result(timeout=10)
        except FutureTimeout:
            return 40.0
        except Exception:
            return 40.0

        if earnings is None or earnings.empty:
            return 40.0

        try:
            earnings = earnings.reset_index()
            earnings["Earnings Date"] = pd.to_datetime(earnings["Earnings Date"])
            earnings = earnings.sort_values("Earnings Date", ascending=False)

            recent = earnings[earnings["Earnings Date"] <= base_date]
            if recent.empty:
                return 40.0

            for _, erow in recent.iterrows():
                if "Surprise(%)" in erow.index:
                    s = erow.get("Surprise(%)", None)
                    if s is not None and not pd.isna(s):
                        eps_pct = float(s)
                        return self._surprise_to_score(eps_pct)

            return 40.0
        except Exception:
            return 40.0
