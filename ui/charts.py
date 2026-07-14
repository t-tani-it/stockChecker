"""Plotlyを使用した株価チャート描画モジュール

ローソク足チャート・20日移動平均線・出来高を描画する。
"""

import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from db.schema import get_connection


def fetch_prices_for_chart(ticker_id: int, base_date: str, months: int) -> Optional[pd.DataFrame]:
    """チャート描画用の株価データを DB から取得する。

    Args:
        ticker_id: 銘柄 ID。
        base_date: 基準日（"YYYY-MM-DD" 形式）。
        months: 取得月数（例: 6 → 6 ヶ月前から基準日まで）。

    Returns:
        Optional[pd.DataFrame]: date / open / high / low / close / volume カラムの DataFrame。
                                データが存在しない場合は None。
    """
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


def create_price_chart(ticker_id: int, base_date: str, months: int, ticker_name: str = "") -> go.Figure:
    """Plotly のローソク足チャートを作成する。

    ローソク足・20 日移動平均線・出来高バーを重ねて表示する。
    OHLC データが利用できない場合は折れ線グラフで代替する。

    Args:
        ticker_id: 銘柄 ID。
        base_date: 基準日（"YYYY-MM-DD" 形式）。
        months: 表示期間（月数）。
        ticker_name: チャートタイトルに表示する銘柄名。

    Returns:
        go.Figure: Plotly Figure オブジェクト。データがなくても空の図を返す。
    """
    df = fetch_prices_for_chart(ticker_id, base_date, months)

    fig = go.Figure()

    if df is None or df.empty:
        fig.add_annotation(
            text="株価データがありません (銘柄リスト更新→株価DLを実行してください)",
            showarrow=False,
            font=dict(size=14),
        )
        fig.update_layout(height=300)
        return fig

    has_ohlc = all(c in df.columns and df[c].notna().any() for c in ["open", "high", "low", "close"])

    # go.Candlestick は Plotly のローソク足チャート。4 本値（始値・高値・安値・終値）を指定
    # OHLC（Open/High/Low/Close）データがあればローソク足、なければ折れ線グラフ
    if has_ohlc:
        fig.add_trace(go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            showlegend=False,
        ))
    else:
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df["close"] if "close" in df.columns else df.iloc[:, 0],
            mode="lines",
            name="Close",
            line=dict(color="#00b4d8", width=2),
        ))

    # rolling(20).mean() は 20 日間の移動平均（窓関数）。株価チャートの定番テクニカル指標
    if len(df) >= 20 and "close" in df.columns:
        ma20 = df["close"].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=ma20,
            mode="lines",
            name="20MA",
            line=dict(color="orange", width=1),
        ))

    if "volume" in df.columns and df["volume"].notna().any():
        vol_colors = ["gray"] * len(df)
        fig.add_trace(go.Bar(
            x=df["date"],
            y=df["volume"],
            name="出来高",
            yaxis="y2",
            marker=dict(color="rgba(100,100,100,0.3)"),
            showlegend=True,
        ))

    title = f"{ticker_name} - {months}ヶ月" if ticker_name else f"{months}ヶ月"
    fig.update_layout(
        title=title,
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        yaxis=dict(title="株価"),
        yaxis2=dict(
            title="出来高",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(x=0, y=1.1, orientation="h"),
    )

    return fig