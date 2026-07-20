"""stockChecker 設定モジュール

環境変数（.env ファイル）から各種設定値を読み込み、
データベースパス・API キー・ダウンロード期間などをモジュール定数として提供する。
"""

import os
from dotenv import load_dotenv

# .env ファイルの内容を os.environ に読み込む（環境変数として扱えるようになる）
load_dotenv()

# os.getenv(key, default) は環境変数が未定義の場合にデフォルト値を返す（安全な読み取り）
DB_PATH = os.getenv("DB_PATH", "backtest.db")

# int() で文字列→整数に変換（.env の値はすべて文字列として読まれるため）
SENTIMENT_BATCH_SIZE = int(os.getenv("SENTIMENT_BATCH_SIZE", "50"))
SENTIMENT_MIN_INTERVAL_HOURS = int(os.getenv("SENTIMENT_MIN_INTERVAL_HOURS", "24"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_WAIT_SECONDS = int(os.getenv("RETRY_WAIT_SECONDS", "60"))
USER_AGENT = os.getenv("USER_AGENT", "BacktestSystem/1.0")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
EDINET_API_KEY = os.getenv("EDINET_API_KEY", "")

FINBERT_MODEL_NAME = os.getenv("FINBERT_MODEL_NAME", "ProsusAI/finbert")

PRICE_LOOKBACK_YEARS = int(os.getenv("PRICE_LOOKBACK_YEARS", "10"))
FINANCIAL_LOOKBACK_YEARS = int(os.getenv("FINANCIAL_LOOKBACK_YEARS", "4"))

# JPXが提供する上場銘柄一覧Excel（.xls形式）。毎月第3営業日に更新される。
# 旧CSV（listed_co_j.csv等）は2025年頃に廃止されたため、Excel読み取りに移行。
# 読み取りには xlrd ライブラリが必要（pip install xlrd）。
JPX_TICKER_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"