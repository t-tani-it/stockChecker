"""各ルールのスコアリングとルール発見機構のテスト

各ルールが0-100の範囲のスコアを返すこと、および全9ルールが自動発見されることを検証する。
"""

import os
import pytest
import tempfile

from db.schema import init_db, get_connection


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    """テスト用の一時データベースを作成・初期化し、テストデータを投入するフィクスチャ。

    config.DB_PATH を一時ファイルに差し替え、tickers（2 銘柄）・prices（12 ヶ月分）・
    financials（1 件）のテストデータを投入する。

    Yields:
        None
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    monkeypatch.setattr("config.DB_PATH", db_path)
    init_db()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickers (symbol, name, market) VALUES (?, ?, ?)", ("AAPL", "Apple", "us"))
    cursor.execute("INSERT INTO tickers (symbol, name, market) VALUES (?, ?, ?)", ("7203.T", "Toyota", "japan"))
    # cursor.executemany は同じ SQL を複数のパラメータで繰り返し実行する
    # リスト内包表記 [式 for i, m in enumerate(range(1,13))] で 12 ヶ月分のデータを生成
    cursor.executemany(
        "INSERT INTO prices (ticker_id, date, close, volume) VALUES (?, ?, ?, ?)",
        [
            (1, f"2023-{m:02d}-01", 150 + i * 2, 1000000 + i * 10000)
            for i, m in enumerate(range(1, 13))
        ],
    )
    cursor.execute("""
        INSERT INTO financials (ticker_id, fiscal_year, revenue, operating_income, net_income,
                                total_assets, total_equity, per, pbr, roe, dividend_yield)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (1, 2023, 400000, 120000, 95000, 350000, 150000, 25, 40, 0.25, 0.005))
    conn.commit()
    conn.close()
    yield
    os.unlink(db_path)


def test_momentum_rule():
    """MomentumRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.momentum import MomentumRule
    rule = MomentumRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_value_rule():
    """ValueRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.value import ValueRule
    rule = ValueRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_quality_rule():
    """QualityRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.quality import QualityRule
    rule = QualityRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_low_vol_rule():
    """LowVolRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.low_vol import LowVolRule
    rule = LowVolRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_size_rule():
    """SizeRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.size import SizeRule
    rule = SizeRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_anomaly_rule():
    """AnomalyRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.anomaly import AnomalyRule
    rule = AnomalyRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_text_score_rule():
    """TextScoreRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.text_score import TextScoreRule
    rule = TextScoreRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_sentiment_rule():
    """SentimentRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.sentiment import SentimentRule
    rule = SentimentRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_pead_rule():
    """PeadRule が 0〜100 のスコアを返すことを検証する。"""
    from rules.pead import PeadRule
    rule = PeadRule()
    score = rule.calculate(1, "2024-12-31")
    assert 0 <= score <= 100


def test_discover_rules():
    """discover_rules() が全 9 ルールを発見することを検証する。"""
    from rules.runner import discover_rules
    rules = discover_rules()
    rule_names = [r().name for r in rules]
    expected = ["モメンタム", "バリュー", "クオリティ", "サイズ", "低ボラティリティ", "PEAD", "センチメント", "テキスト特徴", "異常検知"]
    for name in expected:
        assert name in rule_names, f"Missing rule: {name}"


def test_runner_backtest():
    """run_backtest() が全ルールのスコアを計算し、0〜100 の範囲であることを検証する。"""
    from rules.runner import run_backtest
    results = run_backtest("2024-12-31")
    assert len(results) >= 8
    for rule_name, scores in results.items():
        assert len(scores) > 0
        for item in scores:
            assert "ticker_id" in item
            assert "score" in item
            assert 0 <= item["score"] <= 100


def test_ranking_build():
    """build_total_ranking_simple() がスコア降順のランキングを生成することを検証する。"""
    from ui.ranking import build_total_ranking_simple
    mock_results = {
        "モメンタム": [{"ticker_id": 1, "score": 80}, {"ticker_id": 2, "score": 60}],
        "バリュー": [{"ticker_id": 1, "score": 70}, {"ticker_id": 2, "score": 90}],
    }
    ranking = build_total_ranking_simple(mock_results)
    assert len(ranking) == 2
    assert ranking[0]["score"] >= ranking[1]["score"]