"""クオリティ効果（高品質企業が安定したリターンを生む傾向）を測定するルール

ROE・自己資本比率・営業利益率の3要素を加重平均してスコア化する。
"""

from rules.base import BaseRule


class QualityRule(BaseRule):
    """クオリティ効果ルール

    ROE・自己資本比率・営業利益率から企業の質を総合評価する。
    """

    name = "クオリティ"
    description = "ROE・自己資本比率が高い質の良い企業は長期的に安定したリターンを生む"

    def need_financials(self) -> bool:
        """ROE・自己資本・営業利益を参照するため、財務データは必須。

        Returns:
            bool: 常に True。
        """
        return True

    def calculate(self, ticker_id: int, base_date: str) -> float:
        """ROE・自己資本比率・営業利益率を加重平均してクオリティスコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。値が大きいほど企業の質が高い。
                    財務データがない場合は 40.0 を返す。

        注意:
            - ROE は 40%、自己資本比率 30%、営業利益率 30% で加重。
        """
        fin = self.get_latest_financial(ticker_id, base_date)
        if fin is None:
            return 40.0

        roe = fin.get("roe")
        total_equity = fin.get("total_equity")
        total_assets = fin.get("total_assets")
        op_income = fin.get("operating_income")
        revenue = fin.get("revenue")

        score = 0
        weights = 0

        # ROE（自己資本利益率）: 高いほど効率的に利益を生んでいる。最重視 40%
        if roe is not None and roe > 0:
            roe_score = min(100, roe * 200)
            score += roe_score * 0.4
            weights += 0.4

        # 自己資本比率 = 自己資本 ÷ 総資産。高すぎるより適度が理想だが単純化
        if total_equity is not None and total_assets is not None and total_assets > 0:
            eq_ratio = total_equity / total_assets
            eq_score = min(100, eq_ratio * 150)
            score += eq_score * 0.3
            weights += 0.3

        # 営業利益率 = 営業利益 ÷ 売上高。本業の収益性を示す
        if op_income is not None and revenue is not None and revenue > 0:
            margin = op_income / revenue
            margin_score = min(100, margin * 400)
            score += margin_score * 0.3
            weights += 0.3

        if weights == 0:
            return 40.0

        return score / weights