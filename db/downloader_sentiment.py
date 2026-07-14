"""ニュースセンチメントのダウンロード・分析モジュール

NewsAPI / Finnhub からニュースを取得し、FinBERTで感情分析を行い、
結果を indicators テーブルに保存する。
"""

import time
import json
import requests
from datetime import datetime, timedelta
from typing import Optional

from config import (
    SENTIMENT_BATCH_SIZE, SENTIMENT_MIN_INTERVAL_HOURS,
    MAX_RETRIES, RETRY_WAIT_SECONDS,
    NEWSAPI_KEY, FINNHUB_API_KEY, FINBERT_MODEL_NAME,
)
from db.schema import get_connection


# モジュールレベルの変数 _finbert_pipeline を None で初期化 → 初回呼び出し時に pipeline を生成
# 2 回目以降は None でないため、if ブロックを通らずキャッシュされたインスタンスを返す
# このパターンを「シングルトン」と呼ぶ（処理の重い初期化を 1 回だけ実行）
_finbert_pipeline = None


def get_finbert():
    """FinBERT 感情分析パイプラインをシングルトンで取得する。

    初回呼び出し時に transformers.pipeline を初期化し、
    以降はキャッシュされたインスタンスを返す。

    Returns:
        pipeline: Hugging Face の sentiment-analysis パイプライン。
    """
    global _finbert_pipeline
    if _finbert_pipeline is None:
        from transformers import pipeline
        _finbert_pipeline = pipeline(
            "sentiment-analysis",
            model=FINBERT_MODEL_NAME,
            tokenizer=FINBERT_MODEL_NAME,
        )
    return _finbert_pipeline


def analyze_sentiment(texts: list[str]) -> list[dict]:
    """テキストリストに対して FinBERT で感情分析を実行する。

    バッチ処理（32 件単位）で推論を行い、各テキストの感情ラベルと信頼度スコアを返す。

    Args:
        texts: 分析対象のテキストリスト。

    Returns:
        list[dict]: 各要素が {"label": str, "score": float} のリスト。
                    推論失敗要素は {"label": "neutral", "score": 0.5} で補完される。

    注意:
        - バッチ間には 0.1 秒のスリープを入れ、GPU/CPU リソースを節約する。
    """
    pipe = get_finbert()
    results = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            outputs = pipe(batch)
            results.extend(outputs)
        except Exception as e:
            results.extend([{"label": "neutral", "score": 0.5}] * len(batch))
        time.sleep(0.1)
    return results


def fetch_news_newsapi(symbol: str, company_name: str = "") -> list[str]:
    """NewsAPI から銘柄関連のニュース記事を取得する。

    Args:
        symbol: 銘柄シンボル。
        company_name: 企業名（空文字の場合はシンボルのみで検索）。

    Returns:
        list[str]: 記事のタイトル＋説明文のリスト。取得失敗時は空リスト。

    Raises:
        なし（例外は関数内で捕捉される）。
    """
    if not NEWSAPI_KEY:
        return []

    query = f"{symbol} stock"
    if company_name:
        query = f"({symbol} OR {company_name}) stock"

    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 10,
                "apiKey": NEWSAPI_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            articles = resp.json().get("articles", [])
            return [a.get("title", "") + ". " + (a.get("description") or "") for a in articles]
        return []
    except Exception:
        return []


def fetch_news_finnhub(symbol: str) -> list[str]:
    """Finnhub API から過去 7 日間の企業ニュースを取得する。

    Args:
        symbol: 銘柄シンボル。

    Returns:
        list[str]: 記事のヘッドライン＋サマリーのリスト。取得失敗時は空リスト。

    Raises:
        なし（例外は関数内で捕捉される）。
    """
    if not FINNHUB_API_KEY:
        return []

    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol,
                "from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "to": datetime.now().strftime("%Y-%m-%d"),
                "token": FINNHUB_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            articles = resp.json()
            return [a.get("headline", "") + ". " + (a.get("summary") or "") for a in articles[:10]]
        return []
    except Exception:
        return []


def get_next_batch_tickers(n: int, market: str = None) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT t.id, t.symbol, t.name
        FROM tickers t
        LEFT JOIN sentiment_download_log l ON t.id = l.ticker_id
        WHERE t.is_active = 1
    """
    params = []
    if market:
        query += " AND t.market = ?"
        params.append(market)
    query += """
        AND (l.last_downloaded_at IS NULL
             OR datetime(l.next_download_at) <= datetime('now'))
        ORDER BY l.last_downloaded_at ASC NULLS FIRST
        LIMIT ?
    """
    params.append(n)
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def save_sentiment_score(ticker_id: int, articles: list[str], scores: list[dict]):
    """感情分析結果を indicators テーブルと sentiment_download_log に保存する。

    Args:
        ticker_id: 銘柄 ID。
        articles: 分析対象の記事リスト。
        scores: analyze_sentiment の戻り値（label / score）。

    Returns:
        None

    Raises:
        sqlite3.Error: DB 書き込みに失敗した場合。
    """
    if not scores:
        return

    pos_count = sum(1 for s in scores if s["label"].lower() == "positive")
    neg_count = sum(1 for s in scores if s["label"].lower() == "negative")
    neu_count = sum(1 for s in scores if s["label"].lower() == "neutral")
    total = len(scores)

    if total == 0:
        return

    score = ((pos_count - neg_count) / total) * 50 + 50
    score = max(0, min(100, score))

    details = {
        "positive": pos_count,
        "negative": neg_count,
        "neutral": neu_count,
        "total": total,
        "scores": [{"text": a[:200], "label": s["label"], "confidence": round(s["score"], 4)}
                    for a, s in zip(articles, scores)],
    }

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO indicators (ticker_id, date, rule_name, score, details_json)
        VALUES (?, ?, 'sentiment', ?, ?)
    """, (ticker_id, today, score, json.dumps(details, ensure_ascii=False)))

    next_dl = (datetime.now() + timedelta(hours=SENTIMENT_MIN_INTERVAL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT OR REPLACE INTO sentiment_download_log
            (ticker_id, last_downloaded_at, next_download_at, articles_count)
        VALUES (?, datetime('now'), ?, ?)
    """, (ticker_id, next_dl, len(articles)))

    conn.commit()
    conn.close()


def download_next_batch(n: int = None, market: str = None):
    """未処理銘柄のセンチメントデータをバッチダウンロード・分析・保存する。

    NewsAPI（優先）→ Finnhub（フォールバック）の順でニュースを取得し、
    FinBERT で感情分析を行った結果を DB に保存する。

    Args:
        n: バッチサイズ（デフォルトは SENTIMENT_BATCH_SIZE）。
        market: 市場フィルタ（"us" / "japan" / None=全市場）。

    Returns:
        None

    注意:
        - ニュースが取得できなかった銘柄は neutral（スコア 50.0）として記録される。
    """
    if n is None:
        n = SENTIMENT_BATCH_SIZE

    batch = get_next_batch_tickers(n, market=market)
    if not batch:
        print("No tickers pending sentiment download.")
        return

    for item in batch:
        ticker_id = item["id"]
        symbol = item["symbol"]
        name = item.get("name") or ""

        print(f"Sentiment: {symbol} ({name})")

        articles = fetch_news_newsapi(symbol, name)
        if not articles:
            articles = fetch_news_finnhub(symbol)

        if not articles:
            save_sentiment_score(ticker_id, [], [{"label": "neutral", "score": 0.5}])
            print(f"  -> No news found, default neutral")
            continue

        scores = analyze_sentiment(articles)
        save_sentiment_score(ticker_id, articles, scores)

        pos = sum(1 for s in scores if s["label"].lower() == "positive")
        neg = sum(1 for s in scores if s["label"].lower() == "negative")
        print(f"  -> {len(articles)} articles, pos={pos}, neg={neg}")

        time.sleep(1)

    print(f"Sentiment batch complete: {len(batch)} tickers")