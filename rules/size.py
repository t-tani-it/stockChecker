"""サイズ効果（小型株が大型株をアウトパフォームする傾向）を測定するルール

時価総額に基づいて小型株ほど高スコアをつける。
"""

from rules.base import BaseRule
from db.schema import get_connection


class SizeRule(BaseRule):
    """サイズ効果ルール

    時価総額が小さい銘柄ほど高スコアを割り当てる。
    """

    name = "サイズ"
    description = "小型株は大型株より長期的に高いリターンを出しやすい"

    SMALL_CAP_THRESHOLD = 2e9
    MID_CAP_THRESHOLD = 1e10
    LARGE_CAP_THRESHOLD = 5e10
    MEGA_CAP_THRESHOLD = 2e11

    def need_financials(self) -> bool:
        """時価総額のみで判定するため、財務データは不要。

        Returns:
            bool: 常に False。
        """
        return False

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """基準日時点の時価総額に基づいてサイズスコアを計算する。

        時価総額 = 基準日終値 × 発行済み株式数 で算出し、
        小型株ほど高スコアを割り当てる。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。
                    - 小型（~20億未満）: 85.0
                    - 中小型（~100億未満）: 70.0
                    - 中型（~500億未満）: 55.0
                    - 大型（~2000億未満）: 40.0
                    - 超大型（2000億以上）: 25.0
                    時価総額不明の場合は 50.0。
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT shares_outstanding FROM tickers WHERE id = ?", (ticker_id,))
        row = cursor.fetchone()
        shares = row["shares_outstanding"] if row else None

        close = None
        if shares is not None and shares > 0:
            cursor.execute(
                "SELECT close FROM prices WHERE ticker_id = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                (ticker_id, base_date),
            )
            price_row = cursor.fetchone()
            if price_row:
                close = price_row["close"]
        conn.close()

        if shares is None or shares <= 0 or close is None or close <= 0:
            return 50.0

        mcap = close * shares

        # 閾値（threshold）で複数のカテゴリに分割した判断基準（ルールベース）
        # 時価総額が小さいほど高スコア（小型株効果の理論に基づく）
        if mcap < self.SMALL_CAP_THRESHOLD:
            return 85.0
        elif mcap < self.MID_CAP_THRESHOLD:
            return 70.0
        elif mcap < self.LARGE_CAP_THRESHOLD:
            return 55.0
        elif mcap < self.MEGA_CAP_THRESHOLD:
            return 40.0
        else:
            return 25.0