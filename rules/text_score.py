"""テキスト特徴（決算書の楽観性）を測定するルール

事前計算されたテキストスコアを indicators テーブルから読み取り、
フォールバックとしてROEベースの簡易スコアを返す。
"""

from rules.base import BaseRule


class TextScoreRule(BaseRule):
    """テキスト特徴ルール

    事前計算されたテキストスコア（決算書の楽観性）を indicators テーブルから取得する。
    フォールバックとして ROE ベースの簡易スコアを返す。
    """

    name = "テキスト特徴"
    description = "決算書の文章が「楽観的」な企業は、その後の株価が上がりやすい"

    def need_financials(self) -> bool:
        """フォールバックで ROE を参照するため、財務データは必須。

        Returns:
            bool: 常に True。
        """
        return True

    # フォールバック（fallback）: 本来のデータが存在しない場合の代替処理
    # テキスト分析結果があればそれを優先し、なければ ROE で簡易推定する
    def calculate(self, ticker_id: int, base_date: str) -> float:
        """テキストスコアまたは ROE ベースのフォールバックスコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のスコア。
                    事前計算済みテキストスコア優先、無い場合は ROE から推定。
                    データが一切ない場合は 40.0。

        注意:
            - ROE フォールバック: ROE > 10% → 65.0, > 5% → 55.0, それ以下 → 45.0
        """
        score = self.get_indicator(ticker_id, base_date, "text_score")
        if score is not None:
            return score

        fin = self.get_latest_financial(ticker_id, base_date)
        if fin is None:
            return 40.0

        roe = fin.get("roe")

        if roe is not None and roe > 0.1:
            return 65.0
        if roe is not None and roe > 0.05:
            return 55.0

        return 45.0