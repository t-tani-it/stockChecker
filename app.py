"""stockChecker メインエントリポイント

Streamlit アプリケーションを起動し、バックテストの実行および結果表示を行う。
ユーザーは基準日を選択し「バックテスト実行」ボタンを押すことで、
全ルールによるスコアリング結果をタブ形式で確認できる。
"""

import streamlit as st
from datetime import date

from db.schema import init_db
from rules.runner import discover_rules, run_backtest, get_rule_names
from ui.tabs import render_tab, render_total_tab
from ui.ranking import build_total_ranking_simple


# Streamlit の set_page_config は他の st 描画命令より先に呼ぶ必要がある（最初の描画命令）
st.set_page_config(
    page_title="バックテストシステム",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=3600)
def _run_backtest_cached(base_date_str: str):
    """バックテスト結果をキャッシュする（同一基準日では再計算しない）。"""
    return run_backtest(base_date_str)


def main():
    """Streamlit UI を構築し、バックテストの実行・結果表示を制御する。

    左カラムに基準日選択、右カラムに実行ボタンを配置し、
    バックテスト完了後はルールごとのタブと総合ランキングタブを表示する。

    Args:
        なし

    Returns:
        None

    Raises:
        なし（Streamlit の内部エラーは st.error でハンドルされない）
    """
    init_db()

    st.title("資産運用 バックテストシステム")
    st.markdown("データマイニングで発見した「法則」を過去データで検証します")

    rules = discover_rules()
    rule_names = get_rule_names()

    st.markdown(
        "<style>"
        "div[data-baseweb='popover'] {"
        "  transform: translateX(18.00vw) translateY(180px) !important;"
        "}"
        "</style>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 3, 2])

    with col1:
        base_date = st.date_input(
            "基準日",
            value=date.today(),
            max_value=date.today(),
        )

    with col3:
        run_button = st.button("バックテスト実行", type="primary")

    # Streamlit の処理モデル: ボタンが押されるとスクリプト全体が上から再実行される
    if run_button:
        base_date_str = base_date.strftime("%Y-%m-%d")
        with st.spinner("バックテスト実行中..."):
            results = _run_backtest_cached(base_date_str)
        st.session_state["results"] = results
        st.session_state["base_date"] = base_date_str
        st.success(f"バックテスト完了！ 基準日: {base_date_str}")

    # st.session_state は Streamlit のセッション変数。再実行後も値が保持される
    if "results" in st.session_state:
        results = st.session_state["results"]
        base_date_str = st.session_state["base_date"]

        tab_names = ["総合ランキング"] + [r.name for r in rules]
        tabs = st.tabs(tab_names)

        total_results = build_total_ranking_simple(results)

        with tabs[0]:
            if total_results:
                render_total_tab(total_results, base_date_str, results)
            else:
                st.info("総合ランキングを計算するにはバックテストを実行してください")

        # enumerate はリストの要素とインデックスを同時に取得する組み込み関数
        for i, rule in enumerate(rules):
            with tabs[i + 1]:
                rule_name = rule.name
                if rule_name in results:
                    render_tab(rule_name, results[rule_name], base_date_str)
                else:
                    st.info(f"「{rule_name}」の結果がありません")

    else:
        st.info("👈 基準日を選択して「バックテスト実行」ボタンを押してください")

        st.markdown("""
        ### 組み込みの法則一覧
        | 法則 | 説明 |
        |------|------|
        | モメンタム | 過去3〜12ヶ月で上昇した銘柄はその後も上昇しやすい |
        | バリュー | 割安株（PBR・PERが低い）は長期的に市場平均を上回りやすい |
        | クオリティ | 質の良い企業（ROE高・自己資本率高）は安定したリターンを生む |
        | サイズ | 小型株は大型株より長期的に高いリターンを出しやすい |
        | 低ボラティリティ | 値動きが小さい株のほうが長期的にリターンが高い |
        | PEAD | 良い決算を出した企業は発表後も上昇しやすい |
        | センチメント | ポジティブニュースが増えると株価が上がりやすい |
        | テキスト特徴 | 決算書の楽観的な文章は株価上昇と相関する |
        | 異常検知 | 出来高・ボラティリティ急増銘柄は大きく動きやすい |
        """)


# __name__ == "__main__" は「このファイルが直接実行されたときだけ実行する」という Python のイディオム
# import されたときは __name__ がファイル名になるので main() は呼ばれない
if __name__ == "__main__":
    main()