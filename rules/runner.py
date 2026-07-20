"""バックテストルール発見・実行・ランキング計算エンジン

rules パッケージ内の BaseRule サブクラスを動的に発見し、
全銘柄に対するスコアリング・結果保存・総合ランキング算出を統括する。

このモジュールの責務:
  discover_rules()      — rules/ 配下のルールファイルを自動発見（プラグイン方式）
  run_backtest()        — 全ルール×全銘柄のバックテストを実行（4フェーズ）
  compute_total_ranking() — 全ルールのスコアを合算し総合ランキングを算出
  save_results()        — バックテスト結果を DB (backtest_results) に保存
  get_rule_names()      — Streamlit UI 用にルール名一覧を返す

run_backtest() のエントリポイントとしての位置づけ:
  app.py（Streamlit） → run_backtest() → 各ルールの calculate()
                                        → save_results() で DB 保存
                                        → compute_total_ranking() で総合順位
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


# =============================================================================
# discover_rules(): rules/ 配下から BaseRule 継承クラスを自動発見
#
# 【仕組み】
#   1. importlib.import_module("rules") で rules パッケージを読み込む
#   2. pkgutil.iter_modules() で rules 配下の全 .py ファイルを走査
#   3. 各ファイル内のクラスを inspect.getmembers() で取得
#   4. issubclass(obj, BaseRule) → BaseRule の子孫のみ抽出
#   5. obj is not BaseRule → 抽象基底クラス自身は除外
#
# 【ポイント】
#   - 新しいルールファイルを rules/ に追加するだけで自動認識される
#   - 設定ファイルの編集や登録作業が一切不要（プラグイン方式）
#   - base.py / runner.py / __init__.py は除外（ルールではないため）
# =============================================================================
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


def run_backtest(base_date: str, progress_callback=None) -> Dict[str, List[dict]]:
    """全ルール・全アクティブ銘柄に対してバックテストを実行する。

    discover_rules() で発見した全ルールを順に実行し、
    各ルールのスコアリング結果を DB に保存する。
    最終的に総合ランキングを計算し、結果辞書を返す。

    Args:
        base_date: 基準日（"YYYY-MM-DD" 形式）。
        progress_callback: 進捗通知用コールバック (message: str, elapsed_sec: float, progress: float) -> None。

    Returns:
        Dict[str, List[dict]]: ルール名をキー、スコアリスト（ticker_id / score）を値とする辞書。

    Raises:
        なし（個別の calculate 例外は 0.0 スコアで補償され、log_error に記録される）。

    前提条件:
        - DB に tickers / prices テーブルのデータが存在すること。
        - discover_rules() で少なくとも 1 つのルールが発見されること。
    """
    # =========================================================================
    # run_backtest() の全体の流れ（4フェーズ）
    #
    # フェーズ1 【データ読み込み】: DB（SQLite）の全テーブルをメモリに一括ロード
    #   tickers  ─→ ticker_ids / tickers_map（分析対象の銘柄一覧）
    #   prices   ─→ all_prices[ticker_id] = DataFrame(date, open, high, low, close, volume)
    #   financials ─→ all_financials[ticker_id] = list[dict]
    #   indicators ─→ all_indicators[ticker_id] = {rule_name: list[{date, score}]}
    #
    # フェーズ2 【データ注入】: ロードした全データを各ルールインスタンスにセット
    #   rule.set_all_prices(all_prices)        # 全銘柄の株価
    #   rule.set_all_financials(...)           # 全銘柄の財務
    #   rule.set_all_indicators(...)           # 全銘柄の事前計算指標
    #   rule.set_tickers_map(tickers_map)     # 銘柄名対応表
    #
    # フェーズ3 【スコアリング】: ルール×全銘柄の二重ループでスコア計算
    #   for rule in rule_instances:           # 各ルールを順に
    #       for ticker in all_tickers:        # 全銘柄をループ
    #           score = rule.calculate(ticker_id, base_date)
    #       → スコア降順ソート → results[rule_name] に格納 → DB保存
    #
    # フェーズ4 【総合ランキング】: 全ルールのスコアをクロス集計
    #   compute_total_ranking(results, all_tickers)
    #   → 複数の法則に同時に適合する銘柄を順位付け
    # =========================================================================
    _t0 = time.time()
    _elapsed = lambda: time.time() - _t0

    # ── フェーズ1-①: ルールクラスの発見 ──
    # rules/ 配下の BaseRule 継承クラスを自動検出し、インスタンス化する
    if progress_callback:
        progress_callback("ルールクラスを読み込み中...", _elapsed(), 0.01)

    rule_classes = discover_rules()
    rule_instances = [cls() for cls in rule_classes]

    # ── フェーズ1-②: DB 接続 ──
    conn = get_connection()
    cursor = conn.cursor()

    # ── フェーズ1-③: 銘柄一覧の取得 ──
    # 株価データが存在する銘柄のみを対象とする（EXISTS でフィルタ）
    if progress_callback:
        progress_callback("銘柄リストを読み込み中...", _elapsed(), 0.02)

    cursor.execute("""
        SELECT id, symbol, name, shares_outstanding
        FROM tickers
        WHERE is_active = 1
          AND EXISTS (SELECT 1 FROM prices WHERE ticker_id = id)
    """)
    # cursor.fetchall() は タプル又は辞書のリストを返す。dict(r) でPython辞書化して all_tickers に格納
    all_tickers = [dict(r) for r in cursor.fetchall()]

    ticker_ids = [t["id"] for t in all_tickers]
    tickers_map = {t["id"]: t for t in all_tickers}

    # ── フェーズ1-④: 株価データの一括ロード（全銘柄・全日付） ──
    # 後で ticker_id で groupby し、all_prices 辞書に分割する
    if progress_callback:
        progress_callback(f"株価データを読み込み中 ({len(ticker_ids)}銘柄)...", _elapsed(), 0.05)

    df_all = pd.read_sql_query(
        "SELECT ticker_id, date, open, high, low, close, volume FROM prices ORDER BY ticker_id, date ASC",
        conn,
    )

    # ── フェーズ1-⑤: 財務データの一括ロード ──
    if progress_callback:
        progress_callback("財務データを読み込み中...", _elapsed(), 0.15)

    df_fin = pd.read_sql_query("SELECT * FROM financials", conn)

    # ── フェーズ1-⑥: 事前計算指標（センチメント・PEAD 等）の一括ロード ──
    if progress_callback:
        progress_callback("指標データを読み込み中...", _elapsed(), 0.20)

    df_ind = pd.read_sql_query("SELECT * FROM indicators", conn)
    # 以降はメモリ上のデータのみで処理するため、DB 接続はここで閉じる
    conn.close()

    # ── フェーズ1-⑦: ロードした DataFrame を ticker_id 単位の辞書に分割 ──
    # prices → all_prices: {ticker_id: DataFrame(date, open, high, low, close, volume)}
    all_prices = {}
    for tid, grp in df_all.groupby("ticker_id"):
        all_prices[tid] = grp.drop(columns="ticker_id").reset_index(drop=True)

    # financials → all_financials: {ticker_id: list[dict]}
    all_financials = {}
    for tid, grp in df_fin.groupby("ticker_id"):
        all_financials[tid] = grp.to_dict("records")

    # indicators → all_indicators: {ticker_id: {rule_name: list[{date, score}]}}
    all_indicators = {}
    for tid, grp in df_ind.groupby("ticker_id"):
        ind_dict = {}
        for _, row in grp.iterrows():
            rn = row["rule_name"]
            if rn not in ind_dict:
                ind_dict[rn] = []
            ind_dict[rn].append({"date": row["date"], "score": row["score"]})
        all_indicators[tid] = ind_dict

    # ── フェーズ2: 各ルールインスタンスに全データをセット ──
    # これにより各ルールの calculate() 内で self.get_prices() / self.get_financial() 等が
    # DB クエリではなくメモリ上の辞書を参照できるようになる
    for rule in rule_instances:
        rule.set_all_prices(all_prices)
        rule.set_all_financials(all_financials)
        rule.set_all_indicators(all_indicators)
        rule.set_tickers_map(tickers_map)

    # ── フェーズ3: ルールごとに全銘柄のスコアを計算 ──
    results = {}
    total_rules = len(rule_instances)

    for i, rule in enumerate(rule_instances):
        rule_name = rule.name
        t0 = time.time()

        progress_pct = 0.25 + (i / total_rules) * 0.70
        if progress_callback:
            progress_callback(f"ルール実行中 ({i+1}/{total_rules}): {rule_name}", _elapsed(), progress_pct)

        ticker_scores = []

        # このルールにおける全銘柄のスコアを計算
        for ticker in all_tickers:
            ticker_id = ticker["id"]
            _tt0 = time.time()
            try:
                score = rule.calculate(ticker_id, base_date)
                ticker_scores.append({"ticker_id": ticker_id, "score": score})
            except Exception as e:
                # エラーが発生した銘柄はスコア0.0として扱い、エラーログに記録
                ticker_scores.append({"ticker_id": ticker_id, "score": 0.0})
                log_error(f"rule_{rule_name}", ticker_id, str(e))
            _tt = time.time() - _tt0
            # 1秒以上かかった銘柄を警告表示（パフォーマンス問題の特定用）
            if _tt > 1.0:
                print(f"[SLOW] {rule_name} ticker_id={ticker_id} {_tt:.1f}s")

        # スコア降順にソートして結果辞書に格納
        ticker_scores.sort(key=lambda x: x["score"], reverse=True)
        results[rule_name] = ticker_scores

        if progress_callback:
            progress_callback(f"保存中: {rule_name}", _elapsed(), progress_pct + 0.02)

        # backtest_results テーブルに保存（Streamlit 再表示時に再利用可能）
        save_results(base_date, rule_name, ticker_scores)

    # ── フェーズ4: 総合ランキングの計算 ──
    # 全ルールのスコアを合算し、どの法則にも当てはまる銘柄を上位表示する
    if progress_callback:
        progress_callback("総合ランキングを計算中...", _elapsed(), 0.96)

    total_results = compute_total_ranking(results, all_tickers)
    save_results(base_date, "総合ランキング", total_results)

    if progress_callback:
        progress_callback("完了", _elapsed(), 1.0)

    return results


# =============================================================================
# compute_total_ranking(): 全ルールのスコアを合算し総合ランキングを算出
#
# 【流れ】
#   1. all_tickers を元に ticker_map を初期化（全銘柄の total_score=0, rule_count=0）
#   2. 各ルールの results を走査:
#      - 各銘柄のスコアを total_score に加算
#      - rule_count をインクリメント（何個のルールでスコアが付いたか）
#   3. スコア降順にソート
#   4. 上位10件のみ返す
#
# 【結果の意味】
#   ・total_score が高い = 複数の法則で高評価
#   ・rule_count  が多い = 多角的に評価されている
# =============================================================================
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


# =============================================================================
# save_results(): バックテスト結果を DB に保存（冪等）
#
# 【流れ】
#   1. 同一 (base_date, rule_name) の既存レコードを全削除
#   2. スコアリストを順位（rank）付きで INSERT
#
# 【冪等性】
#   DELETE → INSERT のため、何度実行しても同じ結果になる
#   → Streamlit の再実行（ボタン連打）で重複が発生しない
#
# 【rank】
#   ticker_scores.sort(reverse=True) 済みのリストを受け取る想定
#   enumerate のインデックス（0始まり）+ 1 を rank として保存
# =============================================================================
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


# =============================================================================
# get_rule_names(): Streamlit UI 用のルール名一覧
#
# discover_rules() と同じ発見ロジックを使い、各ルールの name 属性のみを収集
# → Streamlit のタブ見出し（"モメンタム" 等）として利用される
# =============================================================================
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