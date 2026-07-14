"""バリュー効果（割安株が市場平均を上回る傾向）を測定するルール

PER・PBR・配当利回りを組み合わせて総合的な割安度をスコア化する。
"""

from rules.base import BaseRule


class ValueRule(BaseRule):
    """バリュー効果ルール

    PER・PBR・配当利回りから総合的な割安度をスコアリングする。
    """

    name = "バリュー"
    description = "割安株（PBR・PERが低い）は長期的に市場平均を上回りやすい"

    def need_financials(self) -> bool:
        """PER・PBR・配当利回りを参照するため、財務データは必須。

        Returns:
            bool: 常に True。
        """
        return True

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """PER・PBR・配当利回りを加重平均して割安度スコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。値が大きいほど割安と判定される。
                    財務データがない場合は 40.0 を返す。

        注意:
            - PER は 40%、PBR は 40%、配当利回りは 20% の比率で加重。
        """
        fin = self.get_latest_financial(ticker_id, base_date)
        if fin is None:
            return 40.0

        per = fin.get("per")
        pbr = fin.get("pbr")
        div_yield = fin.get("dividend_yield")

        score = 0
        weights = 0

        # PER と PBR は「低いほど割安」→ 100-per*2 で逆転スコアに
        # 配当利回りは「高いほど良い」（ただし日本の低位株は注意）
        # max(0, min(100, ...)) でスコアを 0〜100 にクリッピング（はみ出し防止）
        if per is not None and per > 0:
            per_score = max(0, min(100, 100 - per * 2))
            score += per_score * 0.4
            weights += 0.4

        if pbr is not None and pbr > 0:
            pbr_score = max(0, min(100, 100 - pbr * 20))
            score += pbr_score * 0.4
            weights += 0.4

        if div_yield is not None and div_yield > 0:
            div_score = min(100, div_yield * 1000)
            score += div_score * 0.2
            weights += 0.2

        # どの指標も取得できなかった場合のデフォルト値（中央より少し低め）
        if weights == 0:
            return 40.0

        # weights で割って加重平均を取る（実際に使えた指標のみで平均）
        return score / weights