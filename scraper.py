"""三保ダム諸量表（過去3日分・正時データ）を取得し、CSVへ重複なく追記する。

https://kanagawa-dam.jp/web_data/genkyo_kokai/quantity_miho.html の表は
JavaScript (DataTables) で描画されており、HTML中の <tbody> は空である。
表の実データはページが内部で呼んでいる JSON API から取得する。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PAGE_URL = "https://kanagawa-dam.jp/web_data/genkyo_kokai/quantity_miho.html"
API_URL = "https://kanagawa-dam.jp/api/quantity-3days.php"
API_PARAMS = {"n": "miho", "interval": "hour"}  # interval: hour(正時) / quarter(15分)

CSV_PATH = Path(__file__).parent / "data" / "miho_dam_history.csv"
CSV_ENCODING = "utf-8-sig"
TIMEOUT = (10, 30)  # (connect, read) seconds

# API のキー -> CSV のカラム名
COLUMNS = {
    "rain": "rain_hourly_mm",                  # 三保ダム上流域雨量 時間(mm)
    "rain_sum": "rain_cumulative_mm",          # 同 累加(mm)
    "v": "water_level_el_m",                   # 貯水位(EL.m)
    "v_active": "effective_storage_1000m3",    # 有効貯水量(千m3)
    "v_per": "effective_storage_pct",          # 有効貯水率(%)
    "in": "inflow_m3s",                        # 三保流入量(m3/s)
    "out_v_etc": "outflow_power_etc_m3s",      # 放流量 発電等(m3/s)
    "out_g": "outflow_gate_m3s",               # 放流量 ゲート(m3/s)
    "out_sum": "outflow_downstream_m3s",       # 放流量 下流(m3/s)
}
TIME_COL = "datetime"
TIME_FORMAT = "%Y-%m-%d %H:%M"
OUT_COLUMNS = [TIME_COL, *COLUMNS.values()]

# どちらも欠測の行は「まだ計測値が確定していない」とみなして保存しない
# （保存してしまうと日時重複で以後スキップされ、欠測のまま固定されるため）
REQUIRED_VALUES = ["rain_hourly_mm", "inflow_m3s"]

log = logging.getLogger("miho-scraper")


class ScrapeError(RuntimeError):
    """取得または解析に失敗したことを表す。"""


def fetch_rows() -> list[dict]:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    headers = {
        "User-Agent": "miho-dam-data-collector (hourly, research use)",
        "Referer": PAGE_URL,
    }
    try:
        resp = session.get(API_URL, params=API_PARAMS, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScrapeError(f"サイトへの接続に失敗しました: {exc}") from exc

    try:
        rows = resp.json()
    except ValueError as exc:
        head = resp.text[:200].replace("\n", " ")
        raise ScrapeError(f"JSONとして解釈できません（サイト構造が変わった可能性）: {head!r}") from exc

    if not isinstance(rows, list) or not rows:
        raise ScrapeError(f"データが空、または想定外の形式です: {type(rows).__name__}, len={len(rows)}")
    return rows


def parse_rows(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    missing = {"dt", *COLUMNS} - set(df.columns)
    if missing:
        raise ScrapeError(
            f"想定カラムがありません（サイト構造が変わった可能性）: {sorted(missing)} / 実際: {sorted(df.columns)}"
        )

    df = df.rename(columns={"dt": TIME_COL, **COLUMNS})[OUT_COLUMNS]
    ts = pd.to_datetime(df[TIME_COL], format=TIME_FORMAT, errors="coerce")
    bad = int(ts.isna().sum())
    if bad:
        log.warning("日時を解釈できない行を %d 件スキップします", bad)
    df = df.assign(**{TIME_COL: ts.dt.strftime(TIME_FORMAT)}).loc[ts.notna()]

    for col in OUT_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")  # "" / "-" / null -> NaN

    incomplete = df[REQUIRED_VALUES].isna().all(axis=1)
    if incomplete.any():
        log.info("計測値が未確定の行を %d 件スキップします: %s", incomplete.sum(), list(df.loc[incomplete, TIME_COL]))
    return df.loc[~incomplete].drop_duplicates(TIME_COL, keep="last").reset_index(drop=True)


def load_history() -> pd.DataFrame:
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        return pd.DataFrame(columns=OUT_COLUMNS)
    hist = pd.read_csv(CSV_PATH, encoding=CSV_ENCODING, dtype={TIME_COL: str})
    if list(hist.columns) != OUT_COLUMNS:
        raise ScrapeError(f"既存CSVのカラムが想定と異なります: {list(hist.columns)}")
    return hist


def update_csv(new: pd.DataFrame) -> int:
    """既存CSVに無い日時の行だけを追記し、日時昇順で保存する。追加行数を返す。"""
    hist = load_history()
    fresh = new[~new[TIME_COL].isin(hist[TIME_COL])]
    if fresh.empty:
        return 0

    merged = pd.concat([hist, fresh], ignore_index=True).sort_values(TIME_COL, kind="stable")
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    merged.to_csv(tmp, index=False, encoding=CSV_ENCODING)
    os.replace(tmp, CSV_PATH)  # 書き込み途中で落ちても既存CSVを壊さない
    return len(fresh)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        new = parse_rows(fetch_rows())
        added = update_csv(new)
    except ScrapeError as exc:
        log.error("%s", exc)
        return 1
    except Exception:
        log.exception("予期しないエラー")
        return 1

    log.info("取得 %d 件 / 新規追加 %d 件 -> %s", len(new), added, CSV_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
