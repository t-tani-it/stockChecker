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

    df = pd.read_sql_query("""
        SELECT date, open, high, low, close, volume
        FROM prices
        WHERE ticker_id = ? AND date >= ? AND date <= ?
        ORDER BY date ASC
    """, conn, params=(ticker_id, start.strftime("%Y-%m-%d"), base_date))
    conn.close()

    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=3600)
def create_price_chart(ticker_id: int, base_date: str, months: int, ticker_name: str = "") -> bytes:
    df = fetch_prices_for_chart(ticker_id, base_date, months)

    W, H = 800, 400
    L, R = 60, 780
    TOP = 40
    CHART_BOTTOM = 255
    VOL_TOP = 265
    VOL_BOTTOM = 320
    BOTTOM = 350
    CHART_H = CHART_BOTTOM - TOP
    CHART_W = R - L
    VOL_H = VOL_BOTTOM - VOL_TOP

    UP = "#00cc96"
    DOWN = "#ef553b"
    VOL_UP = "#99e6cb"
    VOL_DOWN = "#f7aa9d"

    img = Image.new("RGB", (W, H), "#ffffff")
    draw = ImageDraw.Draw(img)
    font_s = ImageFont.truetype(_FONT_PATH, 11)
    font_m = ImageFont.truetype(_FONT_PATH, 13)
    font_l = ImageFont.truetype(_FONT_PATH, 15)

    def _px_y(price_val: float, p_min: float, p_range: float) -> float:
        return CHART_BOTTOM - (price_val - p_min) / p_range * CHART_H

    no_data = df is None or df.empty
    if no_data:
        draw.text((W // 2, H // 2), "株価データがありません", fill="#888", font=font_m, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    n = len(df)
    price_min = df["low"].min()
    price_max = df["high"].max()
    price_range = price_max - price_min or 1
    vol_max = max(df["volume"].max(), 1)

    for i in range(6):
        y = TOP + CHART_H * i // 5
        draw.line([(L, y), (R, y)], fill="#e8e8e8", width=1)
        pv = price_max - price_range * i / 5.
        draw.text((L - 4, y), f"{pv:.0f}", fill="#888", font=font_s, anchor="rm")

    candle_w = max(2, CHART_W // n - 2)
    for i in range(n):
        x = L + CHART_W * i // n
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

        draw.line([(x, y_h), (x, y_l)], fill="#ccc", width=1)
        if abs(c - o) > 1e-10:
            draw.rectangle(
                [x - candle_w // 2, min(y_o, y_c), x + candle_w // 2, max(y_o, y_c)],
                fill=body_color, outline=None,
            )
        else:
            draw.line([(x - candle_w // 2, y_o), (x + candle_w // 2, y_c)], fill=body_color, width=2)

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

    for i in range(n):
        x = L + CHART_W * i // n
        v = df["volume"].iloc[i]
        vh = max(1, v / vol_max * VOL_H)
        vol_color = VOL_UP if df["close"].iloc[i] >= df["open"].iloc[i] else VOL_DOWN
        draw.rectangle(
            [x - candle_w // 2, VOL_BOTTOM - vh, x + candle_w // 2, VOL_BOTTOM],
            fill=vol_color, outline=None,
        )

    for idx in [0, n // 4, n // 2, 3 * n // 4, n - 1]:
        if idx < n:
            x = L + CHART_W * idx // n
            draw.text((x, BOTTOM), df["date"].iloc[idx].strftime("%m/%d"), fill="#888", font=font_s, anchor="mt")

    title = f"{ticker_name} - {months}ヶ月" if ticker_name else f"{months}ヶ月"
    draw.text((L, 10), title, fill="#333", font=font_l, anchor="lt")
    if ma20 is not None and ma20.notna().any():
        draw.text((R, 10), "20MA", fill="#ffa500", font=font_s, anchor="rt")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
