"""ニュースセンチメント効果を測定するルール

事前にダウンロード・分析されたセンチメントスコアを indicators テーブルから読み取る。
"""

from rules.base import BaseRule


class SentimentRule(BaseRule):
    """ニュースセンチメント効果ルール

    indicators テーブルから FinBERT による事前計算済みのセンチメントスコアを読み取る。
    """

    name = "センチメント"
    description = "ポジティブニュースが増えると短期的に株価が上がりやすい"

    def need_financials(self) -> bool:
        """センチメントは indicators テーブルから取得するため、財務データは不要。

        Returns:
            bool: 常に False。
        """
        return False

    # このルールはスコア計算を外部（downloader_sentiment.py）に委譲している
    # 自分の役割は indicators テーブルから既存の結果を読み取ることだけ
    def calculate(self, ticker_id: int, base_date: str) -> float:
        """事前計算されたセンチメントスコアを indicators テーブルから読み取る。

        Args:
            ticker_id: 評価対象の銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0〜100 のセンチメントスコア。
                    未計算の場合は 40.0（中立よりやや低め）を返す。
        """
        score = self.get_indicator(ticker_id, base_date, "sentiment")
        if score is None:
            return 40.0
        return score