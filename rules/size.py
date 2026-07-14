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
        """時価総額に基づいてサイズスコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式、Size ルールでは未使用）。

        Returns:
            float: 0〜100 のスコア。
                    - 小型（~20億未満）: 85.0
                    - 中小型（~100億未満）: 70.0
                    - 中型（~500億未満）: 55.0
                    - 大型（~2000億未満）: 40.0
                    - 超大型（2000億以上）: 25.0
                    時価総額不明の場合は 50.0。

        前提条件:
            - tickers テーブルの market_cap に値が設定されていること。
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT market_cap FROM tickers WHERE id = ?", (ticker_id,))
        row = cursor.fetchone()
        conn.close()

        mcap = row["market_cap"] if row else None

        if mcap is None or mcap <= 0:
            return 50.0

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