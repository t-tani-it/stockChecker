"""バックテストルール発見・実行・ランキング計算エンジン

rules パッケージ内の BaseRule サブクラスを動的に発見し、
全銘柄に対するスコアリング・結果保存・総合ランキング算出を統括する。
"""

import importlib
import inspect
import pkgutil
import time
from typing import List, Type, Dict
from collections.abc import Callable

import pandas as pd

from rules.base import BaseRule
from db.schema import get_connection, log_error


# importlib / pkgutil / inspect は Python のリフレクション機能 — 実行中にコード自身を調べる
# pkgutil.iter_modules でパッケージ内の全 .py ファイルを走査し、BaseRule 継承クラスのみ抽出する
# 新しいルールファイルを rules/ に置くだけで自動認識される（設定ファイルの編集不要）
def discover_rules() -> List[Type[BaseRule]]:
    """rules パッケージから BaseRule の具象サブクラスを動的に発見する。

    pkgutil.iter_modules で rules 配下の全モジュールを走査し、
    BaseRule を継承する具象クラスのみを抽出する（base / runner / __init__ は除外）。

    Returns:
        List[Type[BaseRule]]: 発見されたルールクラスのリスト。

    使用例:
        >>> rules = discover_rules()
        >>> len(rules)
        8

    注意:
        - モジュールのインポート順は不定である。
        - 同一ルールが重複して発見されることはない。
    """
    rules = []
    package = importlib.import_module("rules")

    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if modname in ("base", "runner", "__init__"):
            continue
        module = importlib.import_module(f"rules.{modname}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseRule) and obj is not BaseRule:
                rules.append(obj)

    return rules


def run_backtest(base_date: str) -> Dict[str, List[dict]]:
    """全ルール・全アクティブ銘柄に対してバックテストを実行する。

    discover_rules() で発見した全ルールを順に実行し、
    各ルールのスコアリング結果を DB に保存する。
    最終的に総合ランキングを計算し、結果辞書を返す。

    Args:
        base_date: 基準日（"YYYY-MM-DD" 形式）。

    Returns:
        Dict[str, List[dict]]: ルール名をキー、スコアリスト（ticker_id / score）を値とする辞書。

    Raises:
        なし（個別の calculate 例外は 0.0 スコアで補償され、log_error に記録される）。

    前提条件:
        - DB に tickers / prices テーブルのデータが存在すること。
        - discover_rules() で少なくとも 1 つのルールが発見されること。
    """
    rule_classes = discover_rules()
    rule_instances = [cls() for cls in rule_classes]

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, symbol, name
        FROM tickers
        WHERE is_active = 1
          AND EXISTS (SELECT 1 FROM prices WHERE ticker_id = id)
    """)
    all_tickers = [dict(r) for r in cursor.fetchall()]
    conn.close()

    ticker_ids = [t["id"] for t in all_tickers]
    print(f"Loading prices for {len(ticker_ids)} tickers...")
    conn = get_connection()
    df_all = pd.read_sql_query(
        "SELECT ticker_id, date, open, high, low, close, volume FROM prices ORDER BY ticker_id, date ASC",
        conn,
    )
    conn.close()
    all_prices = {}
    for tid, grp in df_all.groupby("ticker_id"):
        all_prices[tid] = grp.drop(columns="ticker_id").reset_index(drop=True)
    print(f"Loaded {len(all_prices)} tickers' prices")

    for rule in rule_instances:
        rule.set_all_prices(all_prices)

    results = {}

    for rule in rule_instances:
        rule_name = rule.name
        t0 = time.time()
        print(f"Running rule: {rule_name}")
        ticker_scores = []

        # 個別銘柄の計算で例外が発生しても 0.0 で補完して続行（フォールトトレランス）
        # エラーは log_error で DB に記録される
        for ticker in all_tickers:
            ticker_id = ticker["id"]
            try:
                score = rule.calculate(ticker_id, base_date)
                ticker_scores.append({"ticker_id": ticker_id, "score": score})
            except Exception as e:
                ticker_scores.append({"ticker_id": ticker_id, "score": 0.0})
                log_error(f"rule_{rule_name}", ticker_id, str(e))

        ticker_scores.sort(key=lambda x: x["score"], reverse=True)
        results[rule_name] = ticker_scores
        print(f"  -> {len(ticker_scores)} scores in {time.time()-t0:.1f}s")

        save_results(base_date, rule_name, ticker_scores)

    total_results = compute_total_ranking(results, all_tickers)
    save_results(base_date, "総合ランキング", total_results)

    return results


def compute_total_ranking(
    rule_results: Dict[str, List[dict]], all_tickers: List[dict]
) -> List[dict]:
    """全ルールのスコアを合算し、総合ランキング（上位 10 件）を計算する。

    Args:
        rule_results: ルール名をキー、スコアリストを値とする辞書。
        all_tickers: 全アクティブ銘柄のリスト（id / symbol / name）。

    Returns:
        List[dict]: 上位 10 銘柄のランキングリスト。
                    各要素は {"ticker_id": int, "total_score": float, "rule_count": int, "score": float}。

    注意:
        - スコアが未計算のルールは合算対象から除外される。
        - 同一銘柄が複数回出現することはない。
    """
    ticker_map = {}
    for t in all_tickers:
        ticker_map[t["id"]] = {"ticker_id": t["id"], "total_score": 0, "rule_count": 0}

    for rule_name, scores in rule_results.items():
        for item in scores:
            tid = item["ticker_id"]
            if tid in ticker_map:
                ticker_map[tid]["total_score"] += item["score"]
                ticker_map[tid]["rule_count"] += 1

    rankings = list(ticker_map.values())
    for r in rankings:
        if r["rule_count"] > 0:
            r["score"] = r["total_score"]
        else:
            r["score"] = 0

    rankings.sort(key=lambda x: x["score"], reverse=True)
    return rankings[:10]


def save_results(base_date: str, rule_name: str, scores: List[dict]) -> None:
    """バックテスト結果をデータベースの backtest_results テーブルに保存する。

    同一基準日・同一ルールの既存レコードを削除してから INSERT する（冪等性保証）。

    Args:
        base_date: 基準日（"YYYY-MM-DD" 形式）。
        rule_name: ルール名称。
        scores: 保存するスコアリスト。各要素は {"ticker_id": int, "score": float}。

    Returns:
        None

    Raises:
        sqlite3.Error: DB 操作に失敗した場合。

    注意:
        - 順位（rank）は scores のインデックスから自動採番される（1 始まり）。
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM backtest_results WHERE base_date = ? AND rule_name = ?", (base_date, rule_name))

    for rank, item in enumerate(scores):
        cursor.execute("""
            INSERT INTO backtest_results (base_date, rule_name, ticker_id, score, rank)
            VALUES (?, ?, ?, ?, ?)
        """, (base_date, rule_name, item["ticker_id"], item["score"], rank + 1))

    conn.commit()
    conn.close()


def get_rule_names() -> List[str]:
    """全ルールの名称リストを取得する。

    discover_rules() で発見した各ルールクラスをインスタンス化し、
    name 属性を収集して返す。

    Returns:
        List[str]: ルール名称のリスト。

    使用例:
        >>> get_rule_names()
        ['モメンタム', 'バリュー', 'クオリティ', ...]
    """
    rules = discover_rules()
    return [cls().name for cls in rules]