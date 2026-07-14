"""ランキングデータ構築モジュール

各ルールのスコアリング結果を統合し、総合ランキングデータを生成する。
"""

from typing import Dict, List


# 辞書に銘柄ごとのスコアを累積 → スコア降順にソート → ランキング
# このパターン（集約→ソート）はランキング生成の基本的なアルゴリズム
def build_ranking_data(
    rule_results: Dict[str, List[dict]]
) -> List[dict]:
    """全ルールのスコアを銘柄ごとに集約し、総合スコア順にソートされたランキングを生成する。

    Args:
        rule_results: ルール名をキー、スコアリストを値とする辞書。

    Returns:
        List[dict]: 各要素が {"ticker_id": int, "total_score": float, "rules": {rule_name: score}} のリスト。
                    総合スコア降順。

    使用例:
        >>> build_ranking_data({"モメンタム": [{"ticker_id": 1, "score": 80}]})
        [{'ticker_id': 1, 'total_score': 80, 'rules': {'モメンタム': 80}}]
    """
    ticker_scores = {}

    for rule_name, scores in rule_results.items():
        for item in scores:
            tid = item["ticker_id"]
            if tid not in ticker_scores:
                ticker_scores[tid] = {
                    "ticker_id": tid,
                    "total_score": 0,
                    "rules": {},
                }
            ticker_scores[tid]["total_score"] += item["score"]
            ticker_scores[tid]["rules"][rule_name] = item["score"]

    ranking = list(ticker_scores.values())
    ranking.sort(key=lambda x: x["total_score"], reverse=True)
    return ranking


def build_total_ranking_simple(results: Dict[str, List[dict]]) -> List[dict]:
    """シンプルな総合ランキングを生成する（ルール別内訳なし）。

    build_ranking_data の軽量版。総合スコアのみを保持したランキングリストを返す。

    Args:
        results: ルール名をキー、スコアリストを値とする辞書。

    Returns:
        List[dict]: 各要素が {"ticker_id": int, "score": float} のリスト。
                    総合スコア降順。

    使用例:
        >>> build_total_ranking_simple({"モメンタム": [{"ticker_id": 1, "score": 80}]})
        [{'ticker_id': 1, 'score': 80}]
    """
    ticker_scores = {}
    for rule_name, scores in results.items():
        for item in scores:
            tid = item["ticker_id"]
            if tid not in ticker_scores:
                ticker_scores[tid] = {"ticker_id": tid, "total_score": 0, "rules": {}}
            ticker_scores[tid]["total_score"] += item["score"]
            ticker_scores[tid]["rules"][rule_name] = item["score"]

    ranking = list(ticker_scores.values())
    ranking.sort(key=lambda x: x["total_score"], reverse=True)

    result_list = []
    for r in ranking:
        result_list.append({
            "ticker_id": r["ticker_id"],
            "score": r["total_score"],
        })

    return result_list