# NC-Time-Twin

NC-Time-Twin 是一套 NC-Code / G-code 加工時間估測工具，可解析 NC 程式、建立 IR 中介模型、計算刀具路徑幾何與加工時間，並輸出 JSON、CSV、Excel、HTML 報表。

## 主要功能

- 支援 `G00/G01/G02/G03/G04/G17/G18/G19/G20/G21/G28/G30/G80/G81/G82/G83/G90/G91/G93/G94/G95`
- 支援 `M01/M03/M04/M05/M06/M08/M09/M30`
- 支援線段、IJK 圓弧、R 圓弧近似、G81/G82/G83 固定循環展開
- 估算快速移動、切削、圓弧、dwell、換刀、主軸、切削液、optional stop、reference return 時間
- 支援 feed 單位判斷、feed sanity 檢查、進給值正規化
- 支援優化前後 NC 檔比較與退化檢查
- 提供 CLI 與 PySide6 GUI

## 安裝

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

若未安裝成套件，可先設定：

```powershell
$env:PYTHONPATH="src"
```

## CLI 使用

估測加工時間：

```powershell
python -m nc_time_twin estimate --nc examples/basic.nc --profile profiles/default_3axis.yaml --out output/basic.xlsx
```

比較優化前後 NC：

```powershell
python -m nc_time_twin estimate --nc examples/ToolPathSource.opti.nc --compare-nc examples/ToolPathSource.nc --profile profiles/default_3axis.yaml --fail-on-regression --out output/compare.xlsx
```

正規化 G21/G94 進給值：

```powershell
python -m nc_time_twin normalize-feed --nc input.nc --profile profiles/default_3axis.yaml --input-feed-unit m_per_min --out output/input.normalized.nc
```

## GUI 使用

```powershell
python -m nc_time_twin.gui.main_window
```
or
```powershell
nc-time-twin-gui
```

GUI 可選擇 NC 檔與 machine profile，執行估測後查看 summary、block 明細、警告與圖表，並可匯出報表。

## 輸出

指定 `--out` 可輸出 `json`、`csv`、`xlsx`、`html`。每次估測也會自動產生：

- `output/Report_<NC檔名>_<yyyyMMdd_HHmm>.xlsx`
- `logs/<NC檔名>_<yyyyMMdd_HHmm>.log`

## 文件

- [專案介紹報告](docs/專案介紹報告.md)
- [使用者手冊](docs/使用者手冊.md)
- [系統架構](docs/系統架構.md)
- [參數設定說明](docs/參數設定說明.md)

## 測試

```powershell
pytest
```
