# INTERFACE.md - インターフェース仕様

## 1. 起動方法
```bash
cd aaa
pip install -r requirements.txt
streamlit run app.py
# → http://localhost:8501 で起動
```

## 2. UI画面構成

### 2.1 ヘッダー（全画面共通）
```
[基準日: YYYY-MM-DD ▼]  [バックテスト実行]
```

### 2.2 タブ一覧（左から順）
```
[総合ランキング] [モメンタム] [バリュー] [クオリティ] [サイズ]
[低ボラティリティ] [PEAD] [センチメント] [テキスト特徴] [異常検知]
```

### 2.3 各タブの表示内容
```
┌─────────────────────────────────────────────┐
│ 適合銘柄一覧（スコア降順）                   │
│                                              │
│ # │ 銘柄名 │ スコア │ グラフ                │
│ ──┼────────┼────────┼───────                │
│ 1 │ XXX    │ 89    │ [6ヶ月グラフ]          │
│   │        │       │ [3m][6m][9m][12m]切替  │
│ 2 │ YYY    │ 72    │ [...]                  │
└─────────────────────────────────────────────┘
```

### 2.4 総合ランキングタブ
```
┌─────────────────────────────────────────────┐
│ 全指標クロス集計 TOP10                      │
│                                              │
│ # │銘柄│合計│モメ│バリ│クオ│サイ│低ボ│...  │ グラフ
│ ──┼────┼───┼───┼───┼───┼───┼───┼──────│
│ 1 │ A  │445│ 89│ 88│ 76│ 45│ 92│ 55│ [📈]  │
│ 2 │ B  │432│ 76│ 92│ 85│ 34│ 78│ 67│ [📈]  │
└─────────────────────────────────────────────┘
```

## 3. 操作手順

### 3.1 初回セットアップ
```python
# 1. 銘柄リストを更新
python -c "from db.tickers import update_ticker_list; update_ticker_list()"

# 2. 株価データをDL（初回は全銘柄）※時間がかかる
python -c "from db.downloader_prices import download_all; download_all()"

# 3. 財務データをDL（初回は4年分）
python -c "from db.downloader_financials import download_all; download_all()"

# 4. センチメントデータをDL（順次）
python -c "from db.downloader_sentiment import download_next_batch; download_next_batch(n=50)"
```

### 3.2 定期更新
```python
# 株価差分更新（前回DL以降のみ）
python -c "from db.downloader_prices import update_incremental; update_incremental()"

# 財務データ蓄積更新（新しい年度のみ追加）
python -c "from db.downloader_financials import update_accumulate; update_accumulate()"

# センチメント続きをDL（未DL銘柄から順に）
python -c "from db.downloader_sentiment import download_next_batch; download_next_batch(n=50)"
```

### 3.3 バックテスト実行
```python
# プログラムから直接
python -c "
from rules.runner import run_backtest
run_backtest(base_date='2024-01-15')
"

# または Streamlit UI から基準日選択 → 実行ボタン
```

## 4. プラグイン追加方法

```python
# rules/custom_rule.py
from rules.base import BaseRule

class CustomRule(BaseRule):
    name = "独自法則"
    description = "独自に発見した法則"

    def need_financials(self) -> bool:
        return False

    def calculate(self, ticker_id: int, base_date: date) -> float:
        prices = self.get_prices(ticker_id, base_date, lookback_days=252)
        score = self._my_algorithm(prices)
        return score
```

## 5. エラーハンドリング

| エラー | 原因 | 対応 |
|--------|------|------|
| TickerNotFound | ティッカー廃止/変更 | スキップしてログ記録 |
| NoDataForDateRange | 上場前の日付 | スコア0として扱う |
| RateLimitError | API制限 | 待機後リトライ（自動） |
| FinbertModelNotFound | 初回起動時 | transformersが自動DL（~438MB） |
