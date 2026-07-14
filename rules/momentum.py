"""モメンタム効果（過去の上昇が継続する傾向）を測定するルール

過去3ヶ月・6ヶ月・12ヶ月のリターンを加重平均し、0-100のスコアに正規化する。
"""

import numpy as np
from rules.base import BaseRule, normalize_score


class MomentumRule(BaseRule):
    """モメンタム効果ルール

    過去 3・6・12 ヶ月のリターンを加重平均し、上昇トレンド銘柄を高スコア評価する。
    """

    name = "モメンタム"
    description = "過去3〜12ヶ月で上昇した銘柄は、その後も上昇しやすい"

    def need_financials(self) -> bool:
        """価格データのみで計算可能なため、財務データは不要。

        Returns:
            bool: 常に False。
        """
        return False

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """過去 3・6・12 ヶ月のリターンを加重平均してスコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。値が大きいほど上昇モメンタムが強い。
                    最低 60 営業日のデータがない場合は 40.0 を返す。

        注意:
            - 3 ヶ月・6 ヶ月・12 ヶ月のリターンを 3:3:4 の比率で加重する。
        """
        df = self.get_prices(ticker_id, base_date, lookback_days=365)
        if df is None or len(df) < 60:
            return 40.0

        closes = df["close"].values
        periods = [63, 126, 252]
        scores = []
        # 各期間のリターン計算: closes[-1] は最新終値、closes[-p] は p 営業日前の終値
        # 配列の末尾が「最新」、先頭が「最古」であるのに注意
        for p in periods:
            if len(closes) >= p:
                ret = (closes[-1] / closes[-p]) - 1
                scores.append(ret)
            else:
                ret = (closes[-1] / closes[0]) - 1
                scores.append(ret)

        momentum_3m, momentum_6m, momentum_12m = scores
        # 短期ほど将来予測にノイズが多いため、12 ヶ月に最も大きい重み 0.4 を割り当てる
        weighted = momentum_3m * 0.3 + momentum_6m * 0.3 + momentum_12m * 0.4

        return normalize_score(weighted, -0.3, 0.5)