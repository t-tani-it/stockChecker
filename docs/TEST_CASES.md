# TEST_CASES.md - テストケース

## テスト実行方法
```bash
cd aaa
pytest tests/ -v
```

## 単体テスト

### TC-001: 銘柄リスト取得
```python
# 正常系: JPXのCSVから日本株リスト取得
tickers_jp = get_jpx_tickers()
assert len(tickers_jp) > 3000  # 東証全銘柄

# 正常系: 米国株リスト取得
tickers_us = get_us_tickers()
assert len(tickers_us) > 5000
```

### TC-002: 株価ダウンロード
```python
# 正常系: 特定銘柄の10年分取得
df = download_price("AAPL", start="2015-01-01")
assert len(df) > 2500  # 約10年分の営業日

# 異常系: 存在しないティッカー
result = download_price("XXXXX")
assert result is None
assert error_log.count() == 1
```

### TC-003: 財務データ蓄積
```python
# 初回: 4年分取得
insert_financials("AAPL", years=4)
assert db.query("SELECT COUNT(*) FROM financials WHERE ticker='AAPL'") == 4

# 更新: 新しい1年分のみ追加（古いデータは保持）
update_financials("AAPL")
assert db.query("SELECT COUNT(*) FROM financials WHERE ticker='AAPL'") == 5
```

### TC-004: 各ルール計算
```python
# モメンタム: 過去12ヶ月上昇銘柄は高スコア
score = MomentumRule().calculate(ticker_id=1, base_date="2024-01-15")
assert 0 <= score <= 100

# バリュー: PBR低いほど高スコア
score = ValueRule().calculate(ticker_id=2, base_date="2024-01-15")
assert 0 <= score <= 100
```

### TC-005: 総合ランキング
```python
results = run_all_rules(base_date="2024-01-15")
top10 = get_top10(results)
assert len(top10) == 10
assert top10[0].total_score >= top10[9].total_score
```

## 結合テスト

### TC-101: フルバックテストフロー
```python
# 1. 銘柄リスト更新 → OK
# 2. 株価DL（3銘柄のみ） → OK
# 3. 財務DL（3銘柄のみ） → OK
# 4. バックテスト実行（基準日=2024-01-15） → OK
# 5. 全タブが正しく表示される → OK
# 6. グラフが6ヶ月デフォルトで表示される → OK
```

### TC-102: エラー耐性
```python
# 廃止銘柄が含まれていても処理が止まらない
# ネットワークエラー時に自動リトライする
# 財務データ欠損銘柄は財務不要ルールのみ評価
```

## 検証用チェックリスト

### データ整合性
- [ ] prices に未来の日付データがない
- [ ] financials に重複する fiscal_year がない
- [ ] backtest_results の基準日がすべて同じ
- [ ] 総合ランキングのスコア = 各ルールスコアの合計

### UI表示
- [ ] 総合ランキングが一番左のタブ
- [ ] グラフデフォルトは6ヶ月
- [ ] 3/6/9/12ヶ月の切替が動作
- [ ] タブごとに適合銘柄のみ表示
- [ ] スコア降順でソート
