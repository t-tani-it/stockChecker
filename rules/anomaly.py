"""異常検知ルール（出来高・ボラティリティ急増銘柄を検出）

直近期間の出来高とボラティリティが過去と比較して急増しているかを測定し、
大きな値動きの予兆としてスコアリングする。
"""

import numpy as np
from rules.base import BaseRule


class AnomalyRule(BaseRule):
    """異常検知ルール

    直近期間（20 日）の出来高・ボラティリティが過去と比較して急増しているかを測定する。
    """

    name = "異常検知"
    description = "出来高やボラティリティが急増した銘柄は、短期的に大きく動きやすい"

    def need_financials(self) -> bool:
        """価格データ（出来高・終値）のみで計算可能なため、財務データは不要。

        Returns:
            bool: 常に False。
        """
        return False

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """出来高比率とボラティリティ比率から異常検知スコアを計算する。

        直近 20 日の平均出来高 / 過去 126 日の平均出来高、および
        直近 20 日のボラティリティ / 過去のボラティリティを測定する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。急増度が高いほど高スコア。
                    最低 40 営業日のデータがない場合は 40.0 を返す。

        注意:
            - 出来高 3 倍以上 +60、2 倍以上 +40、1.5 倍以上 +20。
            - ボラティリティ 2 倍以上 +40、1.5 倍以上 +20。
        """
        df = self.get_prices(ticker_id, base_date, lookback_days=126)
        if df is None or len(df) < 40:
            return 40.0

        volumes = df["volume"].values.astype(float)
        closes = df["close"].values

        if np.std(volumes) == 0:
            return 40.0

        # 直近 20 日の出来高平均 ÷ 過去の出来高平均 → 出来高急増率
        # [+]1e-10 はゼロ除算防止（すべての値が 0 でも割り算が成立するよう微小値を足す）
        recent_vol = volumes[-20:]
        past_vol = volumes[:-20]

        if len(past_vol) < 10:
            return 40.0

        vol_ratio = np.mean(recent_vol) / (np.mean(past_vol) + 1e-10)

        # 対数収益率の標準偏差でボラティリティを測定
        log_returns = np.log(closes[1:] / closes[:-1])
        recent_vola = np.std(log_returns[-20:])
        past_vola = np.std(log_returns[:-20])

        vola_ratio = recent_vola / (past_vola + 1e-10) if len(log_returns) > 20 else 1.0

        score = 0
        if vol_ratio > 3:
            score += 60
        elif vol_ratio > 2:
            score += 40
        elif vol_ratio > 1.5:
            score += 20

        if vola_ratio > 2:
            score += 40
        elif vola_ratio > 1.5:
            score += 20

        return min(100, score + 10)