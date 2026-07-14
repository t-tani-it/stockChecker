# OPERATION_RULES.md - 運用ルール

## 絶対ルール（破ってはいけない）

### RULE 1: DBの直接削除禁止
- backtest.db を手動で削除しない
- テーブルのDROPや全行DELETEをしない
- どうしても必要なら事前にバックアップを取得すること

### RULE 2: データ蓄積の継続
- 更新時は必ず UPSERT（INSERT OR REPLACE）を使用
- 既存データを削除してから再INSERTしない
- 古いデータを新しいデータで上書きしない（新しい年度のみ追加）

### RULE 3: API制限の遵守
| API | 制限 | 推奨待機時間 |
|-----|------|-------------|
| yfinance | 明示的制限なし（2000 req/min程度） | 0.2秒/req |
| NewsAPI | 100 req/day（無料） | 戦略的に使用 |
| Finnhub | 60 req/min（無料） | 1秒/req |
| EDINET API | 制限公開なし | 0.5秒/req |
| sec-edgar-api | 10 req/sec | 0.1秒/req |

### RULE 4: センチメントDLは必ず順次実行
- download_next_batch(n) でN件ずつ処理
- 同一銘柄の再DL間隔は最低24時間あける
- DLログ（sentiment_download_log）を必ず確認してから実行

## 推奨ルール（守ると安全）

### RULE 5: 定期的な運用サイクル
```
毎営業日: 株価差分更新（update_incremental）
四半期ごと: 財務データ更新（update_accumulate）
週1回: センチメントDL（50銘柄ずつ）
月1回: 銘柄リスト更新（update_ticker_list）
```

### RULE 6: バックテスト実行前の確認
1. 基準日時点のデータがDBに存在するか確認
2. 基準日が未来の日付でないことを確認
3. 大量実行する場合はバッチ処理推奨

### RULE 7: エラー対応
- error_log テーブルを定期的に確認
- 連続エラーが発生している銘柄は調査対象
- 3回以上連続エラーの銘柄は自動スキップ

## 設定ファイル（config.py）

```python
# config.py で管理する値
DB_PATH = "backtest.db"
SENTIMENT_BATCH_SIZE = 50     # 1回のDL銘柄数
SENTIMENT_MIN_INTERVAL = 24   # 再DL間隔（時間）
MAX_RETRIES = 3               # 最大リトライ回数
RETRY_WAIT = 60               # リトライ待機秒数
USER_AGENT = "BacktestSystem/1.0"
```

## 禁止行為リスト
- ❌ DBファイルの直接編集
- ❌ 他システムからのDB同時書き込み
- ❌ 基準日より未来の株価を使ったバックテスト
- ❌ センチメントDLの無限ループ実行
- ❌ 財務データの全削除再取得
