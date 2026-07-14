"""低ボラティリティ効果（値動きが小さい株のリターンが高い傾向）を測定するルール

年率換算したヒストリカル・ボラティリティを基準にスコアリングする。
"""

import numpy as np
from rules.base import BaseRule


class LowVolRule(BaseRule):
    """低ボラティリティ効果ルール

    過去 1 年の年率換算ヒストリカル・ボラティリティが低いほど高スコアを割り当てる。
    """

    name = "低ボラティリティ"
    description = "値動きが小さい株のほうが、長期的にリターンが高い"

    def need_financials(self) -> bool:
        """価格データのみで計算可能なため、財務データは不要。

        Returns:
            bool: 常に False。
        """
        return False

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """年率換算ヒストリカル・ボラティリティから低ボラティリティスコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。ボラティリティが低いほど高スコア。
                    最低 60 営業日のデータがない場合は 40.0 を返す。

        注意:
            - 対数収益率の標準偏差 × sqrt(252) で年率換算。
        """
        df = self.get_prices(ticker_id, base_date, lookback_days=252)
        if df is None or len(df) < 60:
            return 40.0

        # closes[1:] = 2 番目以降（今日）, closes[:-1] = 最後以外（昨日）
        # 除算で「今日 ÷ 昨日」のリターン比を計算し、np.log で対数収益率に変換
        # 対数収益率は「連続複利」の仮定に基づくファイナンスの標準手法
        closes = df["close"].values
        log_returns = np.log(closes[1:] / closes[:-1])
        hv = np.std(log_returns) * np.sqrt(252)

        annualized_vol = hv

        if annualized_vol <= 0:
            return 40.0

        # 年率 15% 未満 →「低ボラ」= 90 点。50% 超 →「高ボラ」= 15 点
        # 閾値は過去の市場平均（年率 15〜20%）を参考に設定
        if annualized_vol < 0.15:
            return 90.0
        elif annualized_vol < 0.25:
            return 75.0
        elif annualized_vol < 0.35:
            return 55.0
        elif annualized_vol < 0.50:
            return 35.0
        else:
            return 15.0