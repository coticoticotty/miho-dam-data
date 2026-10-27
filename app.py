"""三保ダム 諸量ダッシュボード (Streamlit).

data/miho_dam_history.csv（scraper.py が毎時追記）を読み込んで可視化する。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

CSV_PATH = Path(__file__).parent / "data" / "miho_dam_history.csv"
CSV_ENCODING = "utf-8-sig"
TIME_COL = "datetime"

LABELS = {
    TIME_COL: "観測日時",
    "rain_hourly_mm": "時間雨量(mm)",
    "rain_cumulative_mm": "累加雨量(mm)",
    "water_level_el_m": "貯水位(EL.m)",
    "effective_storage_1000m3": "有効貯水量(千m³)",
    "effective_storage_pct": "有効貯水率(%)",
    "inflow_m3s": "流入量(m³/s)",
    "outflow_power_etc_m3s": "放流量 発電等(m³/s)",
    "outflow_gate_m3s": "放流量 ゲート(m³/s)",
    "outflow_downstream_m3s": "放流量 下流(m³/s)",
}

# 三保ダムの基準水位 (EL.m)。取得元ページの「三保ダムの定数値」より。
LEVEL_PREP_FLOOD = 316.8  # 洪水貯留準備水位
LEVEL_EMERGENCY = 320.6  # 緊急放流(異常洪水時防災操作)判断水位

# 系列色は「指標ごとに固定」（フィルタで系列数が変わっても色は変えない）
PALETTE = {
    "light": {"rain": "#2a78d6", "inflow": "#eb6834", "level": "#1baf7a", "outflow": "#6250d6", "ref": "#8a8985"},
    "dark": {"rain": "#3987e5", "inflow": "#d95926", "level": "#199e70", "outflow": "#9085e9", "ref": "#9a998f"},
}
GRID = "rgba(128,128,128,0.22)"

PERIODS = {"直近24時間": 24, "直近3日間": 72, "直近7日間": 168, "全期間": None, "カスタム": None}

st.set_page_config(page_title="三保ダム 諸量ダッシュボード", page_icon="💧", layout="wide")

# スマホではカードを2列、数値フォントをやや小さく
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }
    @media (max-width: 640px) {
        .block-container { padding-left: 0.8rem; padding-right: 0.8rem; }
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.25rem 0.5rem; }
        [data-testid="stColumn"], [data-testid="column"] {
            flex: 1 1 calc(50% - 0.5rem) !important; min-width: calc(50% - 0.5rem) !important;
        }
        [data-testid="stMetricValue"] { font-size: 1.5rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=600, show_spinner=False)
def load_data(path: str, mtime: float) -> pd.DataFrame:
    """mtime は CSV 更新時にキャッシュを無効化するためのキー。"""
    df = pd.read_csv(path, encoding=CSV_ENCODING)
    df[TIME_COL] = pd.to_datetime(df[TIME_COL], errors="coerce")
    df = df.dropna(subset=[TIME_COL]).drop_duplicates(TIME_COL, keep="last")
    return df.sort_values(TIME_COL).reset_index(drop=True)


def load_or_stop() -> pd.DataFrame:
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        st.warning(
            f"データファイル `{CSV_PATH.name}` が見つからないか空です。"
            "`python scraper.py` を実行するか、GitHub Actions の初回実行を待ってください。"
        )
        st.stop()
    try:
        df = load_data(str(CSV_PATH), CSV_PATH.stat().st_mtime)
    except Exception as exc:  # 壊れたCSVなど
        st.error(f"CSV を読み込めませんでした: {exc}")
        st.stop()
    missing = set(LABELS) - set(df.columns)
    if missing:
        st.error(f"CSV に想定カラムがありません: {sorted(missing)}")
        st.stop()
    if df.empty:
        st.warning("データが 0 件です。")
        st.stop()
    return df


def theme_colors() -> dict[str, str]:
    try:
        mode = st.context.theme.type  # Streamlit >= 1.46
    except Exception:
        mode = "light"
    return PALETTE["dark" if mode == "dark" else "light"]


def fmt(value, spec: str, unit: str = "") -> str:
    return "–" if pd.isna(value) else f"{value:{spec}}{unit}"


def delta_str(cur, prev, spec: str) -> str | None:
    if pd.isna(cur) or pd.isna(prev):
        return None
    return f"{cur - prev:+{spec}}"


def render_kpis(df: pd.DataFrame) -> None:
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    # 前の行がちょうど1時間前のときだけ「前時間比」を出す（欠測を跨いだ比較を避ける）
    has_prev = prev is not None and (last[TIME_COL] - prev[TIME_COL]) == pd.Timedelta(hours=1)

    def d(col: str, spec: str) -> str | None:
        return delta_str(last[col], prev[col], spec) if has_prev else None

    cards = st.columns(5)
    cards[0].metric("観測日時", last[TIME_COL].strftime("%m/%d %H:%M"))
    cards[1].metric("上流域雨量(時間)", fmt(last.rain_hourly_mm, ".1f", " mm"), d("rain_hourly_mm", ".1f"), delta_color="off")
    cards[2].metric("流入量", fmt(last.inflow_m3s, ".2f", " m³/s"), d("inflow_m3s", ".2f"), delta_color="off")
    cards[3].metric("貯水位", fmt(last.water_level_el_m, ".2f", " EL.m"), d("water_level_el_m", ".2f"), delta_color="off")
    cards[4].metric("放流量(下流)", fmt(last.outflow_downstream_m3s, ".2f", " m³/s"), d("outflow_downstream_m3s", ".2f"), delta_color="off")

    now_jst = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
    lag = now_jst - last[TIME_COL]
    note = "矢印は前の時間との差。" if has_prev else ""
    st.caption(f"{note}最終観測は {lag.total_seconds() / 3600:.1f} 時間前。掲載値は速報値で、後日確定値と異なる場合があります。")
    if lag > pd.Timedelta(hours=6):
        st.warning("最終観測から 6 時間以上経っています。自動収集（GitHub Actions）が止まっていないか確認してください。")


def select_period(df: pd.DataFrame) -> pd.DataFrame:
    latest = df[TIME_COL].max()
    choice = st.radio("表示期間", list(PERIODS), index=1, horizontal=True)

    if choice == "カスタム":
        lo, hi = df[TIME_COL].min().date(), latest.date()
        picked = st.date_input("日付範囲", value=(lo, hi), min_value=lo, max_value=hi)
        if not isinstance(picked, (tuple, list)) or len(picked) != 2:
            st.info("開始日と終了日の両方を選択してください。")
            st.stop()
        start = pd.Timestamp(picked[0])
        end = pd.Timestamp(picked[1]) + pd.Timedelta(days=1)
        return df[(df[TIME_COL] >= start) & (df[TIME_COL] < end)]

    hours = PERIODS[choice]
    if hours is None:
        return df
    return df[df[TIME_COL] > latest - pd.Timedelta(hours=hours)]


def base_layout(fig: go.Figure, height: int) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=36, b=8),
        hovermode="x unified",
        dragmode=False,  # スマホでページスクロールを奪わない
        legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom"),
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, hoverformat="%m/%d %H:%M", tickformat="%m/%d\n%H:%M")
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False, automargin=True)


def rain_inflow_fig(df: pd.DataFrame, c: dict[str, str]) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.4, 0.6])
    fig.add_bar(
        x=df[TIME_COL], y=df.rain_hourly_mm, name="上流域雨量(時間)", marker_color=c["rain"],
        hovertemplate="%{y:.1f} mm", row=1, col=1,
    )
    fig.add_scatter(
        x=df[TIME_COL], y=df.inflow_m3s, name="流入量", mode="lines", line=dict(color=c["inflow"], width=2),
        hovertemplate="%{y:.2f} m³/s", row=2, col=1,
    )
    fig.update_yaxes(title_text="雨量 (mm/h)", rangemode="tozero", row=1, col=1)
    fig.update_yaxes(title_text="流入量 (m³/s)", rangemode="tozero", row=2, col=1)
    base_layout(fig, 520)
    return fig


def level_flow_fig(df: pd.DataFrame, c: dict[str, str]) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.5, 0.5])
    fig.add_scatter(
        x=df[TIME_COL], y=df.water_level_el_m, name="貯水位", mode="lines", line=dict(color=c["level"], width=2),
        hovertemplate="%{y:.2f} EL.m", row=1, col=1,
    )
    fig.add_scatter(
        x=df[TIME_COL], y=df.inflow_m3s, name="流入量", mode="lines", line=dict(color=c["inflow"], width=2),
        hovertemplate="%{y:.2f} m³/s", row=2, col=1,
    )
    fig.add_scatter(
        x=df[TIME_COL], y=df.outflow_downstream_m3s, name="放流量(下流)", mode="lines",
        line=dict(color=c["outflow"], width=2), hovertemplate="%{y:.2f} m³/s", row=2, col=1,
    )

    # 基準水位は、データの近く（±1.5m）にあるときだけ参照線として描く
    lv = df.water_level_el_m.dropna()
    lo, hi = (lv.min(), lv.max()) if not lv.empty else (None, None)
    refs = [(LEVEL_PREP_FLOOD, "洪水貯留準備水位"), (LEVEL_EMERGENCY, "緊急放流判断水位")]
    near = [(v, t) for v, t in refs if lo is not None and lo - 1.5 <= v <= hi + 1.5]
    for v, text in near:
        fig.add_hline(
            y=v, line=dict(color=c["ref"], width=1, dash="dot"), row=1, col=1,
            annotation_text=f"{text} {v}", annotation_position="top left", annotation_font_size=11,
        )
    if lo is not None:
        vals = [lo, hi, *[v for v, _ in near]]
        pad = max((max(vals) - min(vals)) * 0.12, 0.05)
        fig.update_yaxes(range=[min(vals) - pad, max(vals) + pad], row=1, col=1)
    fig.update_yaxes(title_text="貯水位 (EL.m)", row=1, col=1)
    fig.update_yaxes(title_text="流量 (m³/s)", rangemode="tozero", row=2, col=1)
    base_layout(fig, 560)
    return fig


def render_summary(df: pd.DataFrame) -> None:
    total = df.rain_hourly_mm.sum()
    peak_rain = df.rain_hourly_mm.max()
    if df.inflow_m3s.notna().any():
        row = df.loc[df.inflow_m3s.idxmax()]
        peak_in = f"{row.inflow_m3s:.2f} m³/s（{row[TIME_COL]:%m/%d %H:%M}）"
    else:
        peak_in = "–"
    st.caption(f"期間内: 雨量合計 {total:.1f} mm ／ 最大時間雨量 {fmt(peak_rain, '.1f', ' mm')} ／ 最大流入量 {peak_in}")


def main() -> None:
    head, btn = st.columns([5, 1])
    head.title("💧 三保ダム 諸量ダッシュボード")
    if btn.button("🔄 最新データに更新", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    df = load_or_stop()
    render_kpis(df)
    st.divider()

    view = select_period(df)
    if view.empty:
        st.info("選択した期間にデータがありません。")
        st.stop()

    colors = theme_colors()
    render_summary(view)
    tab_rain, tab_dam, tab_table = st.tabs(["雨量・流入量", "貯水位・放流量", "データ表"])
    cfg = {"displayModeBar": False}
    with tab_rain:
        st.plotly_chart(rain_inflow_fig(view, colors), width="stretch", config=cfg)
    with tab_dam:
        st.plotly_chart(level_flow_fig(view, colors), width="stretch", config=cfg)
    with tab_table:
        table = view.sort_values(TIME_COL, ascending=False)
        st.dataframe(
            table.rename(columns=LABELS), hide_index=True, width="stretch", height=420,
            column_config={LABELS[TIME_COL]: st.column_config.DatetimeColumn(LABELS[TIME_COL], format="MM/DD HH:mm")},
        )
        st.download_button(
            f"CSVをダウンロード（{len(view)}件）",
            data=view.assign(**{TIME_COL: view[TIME_COL].dt.strftime("%Y-%m-%d %H:%M")}).to_csv(index=False).encode(CSV_ENCODING),
            file_name=f"miho_dam_{view[TIME_COL].min():%Y%m%d%H%M}_{view[TIME_COL].max():%Y%m%d%H%M}.csv",
            mime="text/csv",
        )


main()
