"""Streamlit UI のタブ描画モジュール

各ルールごとの結果タブと総合ランキングタブをレンダリングする。
"""

import streamlit as st
from typing import Dict, List
from datetime import datetime

from ui.charts import create_price_chart
from db.schema import get_connection


MONTH_OPTIONS = [3, 6, 9, 12]


# ST は Streamlit の標準的な別名。st.* がすべての UI 命令を提供する
# st.columns([1, 3, 1]) は画面を 1:3:1 の比率で横分割するレイアウト機能
# st.expander("タイトル") は折りたたみ可能なセクションを作成する
# st.radio(... horizontal=True) で水平ラジオボタン（デフォルトは縦）
def render_tab(rule_name: str, scores: list, base_date: str) -> None:
    """ルール別の結果タブをレンダリングする。

    スコア上位 50 銘柄をランキング表示し、各銘柄に株価チャートの展開可能セクションを設置する。

    Args:
        rule_name: ルール名称。
        scores: スコアリスト（ticker_id / score）。
        base_date: 基準日（"YYYY-MM-DD" 形式）。

    Returns:
        None
    """
    ticker_map = _get_ticker_map()

    if not scores:
        st.info("該当する銘柄がありません")
        return

    for rank, item in enumerate(scores[:20]):
        ticker_id = item["ticker_id"]
        score = item["score"]
        ticker = ticker_map.get(ticker_id, {})

        symbol = ticker.get("symbol", f"ID:{ticker_id}")
        name = ticker.get("name", "")

        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            st.write(f"**#{rank+1}**")
        with col2:
            st.write(f"{name} ({symbol})")
        with col3:
            st.write(f"Score: **{score:.1f}**")

        expand = st.expander(f"グラフ / {symbol}", expanded=True)
        with expand:
            render_chart_controls(ticker_id, symbol, base_date, rule_name)


def render_total_tab(total_results: list, base_date: str, rule_scores: Dict[str, list]) -> None:
    """総合ランキングタブ（TOP10）をレンダリングする。

    各銘柄の総合スコアとルール別スコアを表示し、株価チャートの展開可能セクションを設置する。

    Args:
        total_results: 総合ランキングリスト（ticker_id / score）。
        base_date: 基準日（"YYYY-MM-DD" 形式）。
        rule_scores: ルール別スコア辞書。

    Returns:
        None
    """
    ticker_map = _get_ticker_map()

    if not total_results:
        st.info("総合ランキングを計算できませんでした")
        return

    st.subheader(f"総合ランキング TOP10 (基準日: {base_date})")

    for rank, item in enumerate(total_results[:10]):
        ticker_id = item["ticker_id"]
        total_score = item["score"]
        ticker = ticker_map.get(ticker_id, {})
        symbol = ticker.get("symbol", f"ID:{ticker_id}")
        name = ticker.get("name", "")

        individual_scores = {}
        for rule_name, scores in rule_scores.items():
            for si in scores:
                if si["ticker_id"] == ticker_id:
                    individual_scores[rule_name] = si["score"]
                    break

        st.markdown(f"### #{rank+1} {name} ({symbol}) - 総合: {total_score:.1f}")

        score_cols = st.columns(min(5, len(individual_scores)))
        for idx, (rname, rscore) in enumerate(list(individual_scores.items())[:5]):
            with score_cols[idx]:
                st.metric(rname, f"{rscore:.1f}")

        expand = st.expander(f"グラフ / {symbol}", expanded=True)
        with expand:
            render_chart_controls(ticker_id, symbol, base_date, "総合")

        st.divider()


def render_chart_controls(ticker_id: int, symbol: str, base_date: str, tab_label: str = "") -> None:
    """株価チャートの期間選択ラジオボタンとチャート描画を制御する。

    Args:
        ticker_id: 銘柄 ID。
        symbol: 銘柄シンボル。
        base_date: 基準日（"YYYY-MM-DD" 形式）。
        tab_label: タブ識別ラベル（キー重複防止用）。

    Returns:
        None
    """
    key_base = f"chart_{tab_label}_{ticker_id}_{symbol}"

    months = st.radio(
        "期間", MONTH_OPTIONS,
        index=MONTH_OPTIONS.index(6),
        horizontal=True,
        key=f"{key_base}_radio",
    )

    fig = create_price_chart(ticker_id, base_date, months, symbol)
    st.image(fig)


# 名前が _ で始まる関数は「内部使用（プライベート）」の慣習 — 外部から呼ばれる想定ではない
def _get_ticker_map() -> Dict[int, dict]:
    """全銘柄の ID → （symbol / name）マッピング辞書を取得する（内部ヘルパー）。

    Returns:
        Dict[int, dict]: ticker_id をキー、{"symbol": str, "name": str} を値とする辞書。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, name FROM tickers")
    # 辞書内包表記: {キー: 値 for 要素 in イテラブル} — ループで辞書を組み立てる Python の簡潔記法
    result = {row["id"]: {"symbol": row["symbol"], "name": row["name"]} for row in cursor.fetchall()}
    conn.close()
    return result