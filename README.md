# 三保ダム 諸量データ自動収集

神奈川県三保ダムの諸量（雨量・流入量・放流量・貯水位）を1時間ごとに取得し、`data/miho_dam_history.csv` に蓄積します。
将来の増水予測モデルの学習データ作成が目的です。

- 取得元: <https://kanagawa-dam.jp/web_data/genkyo_kokai/quantity_miho.html>
- 掲載値は**速報値**で、後日確定値と異なる場合があります。

## 仕組み

上記ページの諸量表は JavaScript で描画されるため、HTML を解析しても表は空です。
ページが内部で呼んでいる JSON API（`/api/quantity-3days.php?n=miho&interval=hour`）から、
**直近3日分（72時間分）の正時データ**を取得します。
GitHub Actions が毎時実行するので、3日分の窓で十分に取りこぼしをカバーできます（3日以上止まると欠損します）。

- 既にCSVにある日時は追記しない（重複排除）。新しい日時だけ末尾に追加し、日時昇順で保存。
- 雨量と流入量が両方とも欠測の行は、値が確定していないとみなして保存しない（次回以降に取り込み）。
- 接続エラー・JSON形式/カラム構成の変更を検出したらエラーログを出し、終了コード1で失敗（Actions が失敗表示になる）。

## CSV カラム

| カラム | 内容 | 単位 |
|---|---|---|
| `datetime` | 計測日時 (`YYYY-MM-DD HH:MM`, JST) | |
| `rain_hourly_mm` | 三保ダム上流域雨量 時間 | mm |
| `rain_cumulative_mm` | 同 累加（無降雨が続くとリセット） | mm |
| `water_level_el_m` | 貯水位 | EL.m |
| `effective_storage_1000m3` | 有効貯水量 | 千m³ |
| `effective_storage_pct` | 有効貯水率 | % |
| `inflow_m3s` | 三保流入量 | m³/s |
| `outflow_power_etc_m3s` | 放流量（発電等） | m³/s |
| `outflow_gate_m3s` | 放流量（ゲート） | m³/s |
| `outflow_downstream_m3s` | 放流量（下流） | m³/s |

エンコーディングは `utf-8-sig`（Excel でそのまま開けます）。

## 手動実行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scraper.py
```

2回続けて実行すると、2回目は「新規追加 0 件」になります。

## GitHub への初回セットアップ

1. GitHub で空のリポジトリを作成する（例: `miho-dam-data`）。
2. このフォルダで:

   ```bash
   git init -b main
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/<USER>/miho-dam-data.git
   git push -u origin main
   ```

3. リポジトリの **Settings → Actions → General → Workflow permissions** が
   "Read and write permissions" になっていることを確認する（`scrape.yml` 側でも `contents: write` を指定済み）。
4. **Actions** タブ → `scrape-miho-dam` → **Run workflow** で手動実行し、`data/miho_dam_history.csv` がコミットされることを確認する。
5. 以降は毎時15分(UTC)に自動実行されます。

注意: GitHub の定期実行は混雑時に数分〜数十分遅れることがあります。
また、Public リポジトリでは60日間リポジトリの動きが無いと定期実行が自動停止されます。
