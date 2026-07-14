"""バックテストルールの抽象基底クラスと共通ユーティリティ

全ルールが継承すべき BaseRule 抽象クラスと、スコア正規化関数を提供する。
BaseRule は価格・財務・指標データの DB 取得メソッドを共通実装として持つ。
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from db.schema import get_connection


# ABC = Abstract Base Class（抽象基底クラス）— 直接インスタンス化できず、継承して使うことを強制する
# @abstractmethod のメソッドはサブクラスで必ずオーバーライドしなければならない（忘れるとエラー）
class BaseRule(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def need_financials(self) -> bool:
        """当該ルールが財務データを必要とするかどうかを返す。

        Returns:
            bool: 財務データが必要な場合は True、不要な場合は False。

        注意:
            - 価格データのみで計算可能なルールは False を返す。
            - 財務指標（PER・PBR・ROE 等）を用いるルールは True を返す。
        """
        pass

    @abstractmethod
    def calculate(self, ticker_id: int, base_date: str) -> float:
        """指定された銘柄・基準日におけるスコアを計算する。

        Args:
            ticker_id: 評価対象の銘柄 ID（tickers テーブルの主キー）。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            float: 0.0〜100.0 の範囲に正規化されたスコア。
                    値が大きいほど有望な銘柄と判定される。

        Raises:
            ValueError: 必要なデータが不足している場合。
        """
        pass

    # @abstractmethod がない = 共通の実装済みメソッド。サブクラスはそのまま使える（必要ならオーバーライドも可）
    # pandas の read_sql_query は SQL の結果を直接 DataFrame として返す（ループ不要で便利）
    def get_prices(self, ticker_id: int, base_date: str, lookback_days: int = 365) -> Optional[pd.DataFrame]:
        """指定銘柄の価格データをデータベースから取得する。

        基準日から過去 lookback_days 日間の日次価格（日付・始値・高値・安値・終値・出来高）を
        昇順で返す。

        Args:
            ticker_id: 銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。
            lookback_days: 取得する過去日数（デフォルト 365 日）。

        Returns:
            Optional[pd.DataFrame]: カラム ['date', 'open', 'high', 'low', 'close', 'volume'] を持つ
                                    DataFrame。データが存在しない場合は None。

        前提条件:
            - prices テーブルに該当 ticker_id のデータが存在すること。
        """
        conn = get_connection()
        end = datetime.strptime(base_date, "%Y-%m-%d")
        start = end - timedelta(days=lookback_days)

        query = """
            SELECT date, open, high, low, close, volume
            FROM prices
            WHERE ticker_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC
        """
        df = pd.read_sql_query(query, conn, params=(ticker_id, start.strftime("%Y-%m-%d"), base_date))
        conn.close()

        if df.empty:
            return None
        return df

    def get_financial(self, ticker_id: int, fiscal_year: int) -> Optional[dict]:
        """指定銘柄・指定年度の財務データを取得する。

        Args:
            ticker_id: 銘柄 ID。
            fiscal_year: 取得対象の会計年度（例: 2023）。

        Returns:
            Optional[dict]: financials テーブルの全カラムを含む辞書。
                            データが存在しない場合は None。

        前提条件:
            - financials テーブルに該当データが存在すること。
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM financials WHERE ticker_id = ? AND fiscal_year = ?",
            (ticker_id, fiscal_year),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_latest_financial(self, ticker_id: int, base_date: str) -> Optional[dict]:
        """指定銘柄の最新財務データを基準日以前から取得する。

        Args:
            ticker_id: 銘柄 ID。
            base_date: 基準日（"YYYY-MM-DD" 形式）。

        Returns:
            Optional[dict]: 最新の financials レコードの辞書。
                            データが存在しない場合は None。

        注意:
            - 基準日の年以前の最新年度データを返す（決算発表ラグを考慮）。
        """
        base_year = int(base_date[:4])
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM financials
            WHERE ticker_id = ? AND fiscal_year <= ?
            ORDER BY fiscal_year DESC
            LIMIT 1
        """, (ticker_id, base_year))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_indicator(self, ticker_id: int, date: str, rule_name: str) -> Optional[float]:
        """事前計算済みのルール別指標値をデータベースから取得する。

        Args:
            ticker_id: 銘柄 ID。
            date: 取得基準日（"YYYY-MM-DD" 形式）。
            rule_name: ルール名称。

        Returns:
            Optional[float]: 指標スコア。データが存在しない場合は None。

        注意:
            - indicators テーブルから指定日以前の最新スコアを取得する。
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT score FROM indicators WHERE ticker_id = ? AND date <= ? AND rule_name = ? ORDER BY date DESC LIMIT 1",
            (ticker_id, date, rule_name),
        )
        row = cursor.fetchone()
        conn.close()
        return row["score"] if row else None


def normalize_score(raw_score: float, min_val: float, max_val: float) -> float:
    """生のスコア値を 0〜100 の範囲に線形正規化する。

    最小値と最大値が等しい場合は中央値 50.0 を返す。
    正規化後は [0, 100] の範囲にクリップされる。

    Args:
        raw_score: 正規化前の生スコア。
        min_val: 全銘柄中の最小スコア。
        max_val: 全銘柄中の最大スコア。

    Returns:
        float: 0.0〜100.0 に正規化されたスコア。

    使用例:
        >>> normalize_score(150.0, 100.0, 200.0)
        50.0
    """
    if max_val == min_val:
        return 50.0
    normalized = (raw_score - min_val) / (max_val - min_val) * 100
    return max(0, min(100, normalized))