"""PEAD（決算サプライズ後のドリフト）を測定するルール

yfinanceから直近の決算サプライズ率を取得し、ポジティブ・サプライズほど高スコアをつける。
"""

import yfinance as yf
import pandas as pd
from rules.base import BaseRule
from db.schema import get_connection


class PeadRule(BaseRule):
    """PEAD（Post-Earnings Announcement Drift）ルール

    直近の決算サプライズ率を yfinance から取得し、
    ポジティブ・サプライズほど高スコアを割り当てる。
    """

    name = "PEAD"
    description = "良い決算を出した企業は、発表後数週間〜数ヶ月上昇しやすい"

    def need_financials(self) -> bool:
        """決算サプライズは yfinance の earnings_dates から直接取得するため不要。

        Returns:
            bool: 常に False。
        """
        return False

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """直近決算のサプライズ率から PEAD スコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。サプライズ率が高いほど高スコア。
                    データ取得失敗時は 40.0 を返す。

        注意:
            - yfinance API のレート制限に影響される可能性がある。
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM tickers WHERE id = ?", (ticker_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return 40.0

        symbol = row["symbol"]

        # ticker.earnings_dates は yfinance が提供する決算発表日とサプライズ率のテーブル
        # reset_index() で日付インデックスを通常カラムに変換し、日付フィルタを可能にする
        try:
            ticker = yf.Ticker(symbol)
            earnings = ticker.earnings_dates

            if earnings is None or earnings.empty:
                return 40.0

            earnings = earnings.reset_index()
            earnings["Earnings Date"] = pd.to_datetime(earnings["Earnings Date"])
            earnings = earnings.sort_values("Earnings Date", ascending=False)

            # 基準日以前の直近決算のみを対象（未来の決算日は除外）
            recent = earnings[earnings["Earnings Date"] <= base_date]
            if recent.empty:
                return 40.0

            latest = recent.iloc[0]

            if "Surprise(%)" not in latest.index:
                return 40.0

            surprise = latest.get("Surprise(%)", 0)
            if pd.isna(surprise):
                return 40.0

            eps_pct = float(surprise)

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
        except Exception:
            return 40.0