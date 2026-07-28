"""Pillowを使用した株価チャート描画モジュール

ローソク足チャート・20日移動平均線・出来高をPNG画像で描画する。
"""

import io
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from db.schema import get_connection


_FONT_PATH = "C:/Windows/Fonts/meiryo.ttc"


@st.cache_data(ttl=3600)
def fetch_prices_for_chart(ticker_id: int, base_date: str, months: int) -> Optional[pd.DataFrame]:
    conn = get_connection()

    end = datetime.strptime(base_date, "%Y-%m-%d")
    start = end - timedelta(days=months * 30)

    # SQLite で日付の絞り込みを行う
    # SQLite は日付型（DATE）を持たないため、date カラムは TEXT（"2024-01-15"）で保存されている
    # TEXT であっても ISO 8601 形式（YYYY-MM-DD）なら文字列比較で正しく大小判定できる
    df = pd.read_sql_query("""
        SELECT date, open, high, low, close, volume
        FROM prices
        WHERE ticker_id = ? AND date >= ? AND date <= ?
        ORDER BY date ASC
    """, conn, params=(ticker_id, start.strftime("%Y-%m-%d"), base_date))
    conn.close()

    if df.empty:
        return None

    # SQLite から読み出した date カラムは、SQLite に日付型が存在しないため文字列（object）型になっている
    # そのままでは .strftime() や日付演算が使えないので、pandas の datetime64[ns] 型に変換する
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=3600)
def create_price_chart(ticker_id: int, base_date: str, months: int, ticker_name: str = "") -> bytes:
    """指定銘柄の株価チャートを Pillow で描画し、PNG バイト列として返す。

    チャート構成（上から順）:
      1. タイトル行
      2. ローソク足 + 20日移動平均線（オレンジ）
      3. 出来高（陽線=緑、陰線=赤）
      4. 日付ラベル（5箇所）
    """
    df = fetch_prices_for_chart(ticker_id, base_date, months)

    # ── キャンバスサイズとレイアウト位置 ──
    W, H = 800, 400           # 全体サイズ（幅800px × 高さ400px）
    L, R = 60, 780            # 左右マージン（左=価格軸、右=20MAラベル用）
    TOP = 40                   # 上マージン（タイトル用）
    CHART_BOTTOM = 255         # ローソク足エリア下端
    VOL_TOP = 265              # 出来高エリア上端
    VOL_BOTTOM = 320           # 出来高エリア下端
    BOTTOM = 350               # 日付ラベル位置
    CHART_H = CHART_BOTTOM - TOP   # ローソク足エリアの高さ
    CHART_W = R - L                # ローソク足エリアの幅
    VOL_H = VOL_BOTTOM - VOL_TOP   # 出来高エリアの高さ

    # ── 色定義 ──
    UP = "#00cc96"            # 陽線（終値 > 始値）：緑
    DOWN = "#ef553b"          # 陰線（終値 < 始値）：赤
    VOL_UP = "#99e6cb"        # 陽線の出来高：薄緑
    VOL_DOWN = "#f7aa9d"      # 陰線の出来高：薄赤

    # ── Pillow 描画準備 ──
    img = Image.new("RGB", (W, H), "#ffffff")
    draw = ImageDraw.Draw(img)
    font_s = ImageFont.truetype(_FONT_PATH, 11)   # 小：日付ラベル・価格ラベル
    font_m = ImageFont.truetype(_FONT_PATH, 13)   # 中：エラーメッセージ
    font_l = ImageFont.truetype(_FONT_PATH, 15)   # 大：タイトル

    # ── 価格→Y座標変換ヘルパー ──
    def _px_y(price_val: float, p_min: float, p_range: float) -> float:
        return CHART_BOTTOM - (price_val - p_min) / p_range * CHART_H

    # ── データ不在時のプレースホルダ ──
    no_data = df is None or df.empty
    if no_data:
        draw.text((W // 2, H // 2), "株価データがありません", fill="#888", font=font_m, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # ── データ範囲の計算 ──
    n = len(df)
    price_min = df["low"].min()
    price_max = df["high"].max()
    price_range = price_max - price_min or 1      # 0除算防止
    vol_max = max(df["volume"].max(), 1)

    # ── グリッド線 + 価格ラベル（5分割） ──
    for i in range(6):
        y = TOP + CHART_H * i // 5
        draw.line([(L, y), (R, y)], fill="#e8e8e8", width=1)
        pv = price_max - price_range * i / 5.
        draw.text((L - 4, y), f"{pv:.0f}", fill="#888", font=font_s, anchor="rm")

    # ── ローソク足描画 ──
    candle_w = max(2, CHART_W // n - 2)
    for i in range(n):
        x = L + CHART_W * i // n   # i 番目のデータ点の X 座標
        o = df["open"].iloc[i]
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        c = df["close"].iloc[i]

        y_h = _px_y(h, price_min, price_range)
        y_l = _px_y(l, price_min, price_range)
        y_o = _px_y(o, price_min, price_range)
        y_c = _px_y(c, price_min, price_range)

        up = c >= o
        body_color = UP if up else DOWN

        # ヒゲ（高値〜安値）
        draw.line([(x, y_h), (x, y_l)], fill="#ccc", width=1)
        # 実体（始値〜終値）
        if abs(c - o) > 1e-10:
            draw.rectangle(
                [x - candle_w // 2, min(y_o, y_c), x + candle_w // 2, max(y_o, y_c)],
                fill=body_color, outline=None,
            )
        else:
            # 始値=終値（十字線）
            draw.line([(x - candle_w // 2, y_o), (x + candle_w // 2, y_c)], fill=body_color, width=2)

    # ── 20日移動平均線（MA20） ──
    ma20 = None
    if len(df) >= 20 and "close" in df.columns:
        ma20 = df["close"].rolling(20).mean()
        for i in range(n - 1):
            v0, v1 = ma20.iloc[i], ma20.iloc[i + 1]
            if pd.notna(v0) and pd.notna(v1):
                x0 = L + CHART_W * i // n
                x1 = L + CHART_W * (i + 1) // n
                y0 = _px_y(v0, price_min, price_range)
                y1 = _px_y(v1, price_min, price_range)
                draw.line([(x0, y0), (x1, y1)], fill="#ffa500", width=2)

    # ── 出来高（棒グラフ） ──
    for i in range(n):
        x = L + CHART_W * i // n
        v = df["volume"].iloc[i]
        vh = max(1, v / vol_max * VOL_H)
        vol_color = VOL_UP if df["close"].iloc[i] >= df["open"].iloc[i] else VOL_DOWN
        draw.rectangle(
            [x - candle_w // 2, VOL_BOTTOM - vh, x + candle_w // 2, VOL_BOTTOM],
            fill=vol_color, outline=None,
        )

    # ── 日付ラベル（5箇所） ──
    # pd.to_datetime() で変換済みの datetime64 なので .strftime() が使える
    for idx in [0, n // 4, n // 2, 3 * n // 4, n - 1]:
        if idx < n:
            x = L + CHART_W * idx // n
            draw.text((x, BOTTOM), df["date"].iloc[idx].strftime("%m/%d"), fill="#888", font=font_s, anchor="mt")

    # ── タイトル ──
    title = f"{ticker_name} - {months}ヶ月" if ticker_name else f"{months}ヶ月"
    draw.text((L, 10), title, fill="#333", font=font_l, anchor="lt")
    if ma20 is not None and ma20.notna().any():
        draw.text((R, 10), "20MA", fill="#ffa500", font=font_s, anchor="rt")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
