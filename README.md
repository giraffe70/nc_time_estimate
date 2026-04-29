# NC-Time-Twin

NC-Time-Twin 是一套 NC-Code / G-code 加工時間估測工具，可解析 NC 程式、建立 IR 中介模型、計算刀具路徑幾何與加工時間，並輸出 JSON、CSV、Excel、HTML 報表。第二階段已加入三軸虛擬控制器時間模型，可用 S-curve、軸向速度/加速度/jerk、junction slowdown 與動態取樣資料提升估測可信度。

## 主要功能

- 支援 `G00/G01/G02/G03/G04/G17/G18/G19/G20/G21/G28/G30/G80/G81/G82/G83/G90/G91/G93/G94/G95`
- 支援 `M01/M03/M04/M05/M06/M08/M09/M30`
- 支援線段、IJK 圓弧、R 圓弧近似、G81/G82/G83 固定循環展開
- 估算快速移動、切削、圓弧、dwell、換刀、主軸、切削液、optional stop、reference return 時間
- 支援 `constant_velocity`、`trapezoid`、`phase2` 三種時間模型
- 第二階段支援三軸 Phase 2 動態模型、junction 診斷、bottleneck 診斷與速度曲線取樣
- 支援 feed 單位判斷、feed sanity 檢查、進給值正規化
- 支援優化前後 NC 檔比較與退化檢查
- 支援 benchmark NC 產生與實測 CSV 校正 Phase 2 profile
- 提供 CLI、PySide6 GUI 與 FastAPI Web UI；優化前後比較集中在 Web UI 與 CLI/API

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

若要使用 console script：

```powershell
pip install -e .
```

## CLI 使用

估測加工時間：

```powershell
python -m nc_time_twin estimate --nc examples/basic.nc --profile profiles/default_3axis.yaml --out output/basic.xlsx
```

使用第二階段三軸虛擬控制器：

```powershell
python -m nc_time_twin estimate --nc examples/basic.nc --profile profiles/default_phase2_3axis.yaml --out output/basic_phase2.xlsx
```

或在既有 profile 上覆寫時間模型：

```powershell
python -m nc_time_twin estimate --nc examples/basic.nc --profile profiles/default_3axis.yaml --time-model phase2 --out output/basic_phase2.xlsx
```

比較優化前後 NC：

```powershell
python -m nc_time_twin estimate --nc examples/ToolPathSource.opti.nc --compare-nc examples/ToolPathSource.nc --profile profiles/default_3axis.yaml --fail-on-regression --out output/compare.xlsx
```

正規化 G21/G94 進給值：

```powershell
python -m nc_time_twin normalize-feed --nc input.nc --profile profiles/default_3axis.yaml --input-feed-unit m_per_min --out output/input.normalized.nc
```

產生第二階段機台校正用 benchmark NC：

```powershell
python -m nc_time_twin generate-benchmark --profile profiles/default_phase2_3axis.yaml --out output/phase2_benchmark.nc --print-summary
```

用實測 CSV 校正 Phase 2 profile：

```powershell
python -m nc_time_twin calibrate-profile --dataset output/calibration.csv --profile profiles/default_phase2_3axis.yaml --out profiles/my_machine_phase2.yaml --print-summary
```

## GUI 使用

```powershell
python -m nc_time_twin.gui.main_window
```

或安裝 package 後：

```powershell
nc-time-twin-gui
```

GUI 提供：

- Project / 估測頁：選擇 NC 與 machine profile，直接設定 feed-unit、time-model、strict-feed、sanity 警示等估測選項。
- Estimate 後：在同一頁顯示中文估測摘要、完整 Results 與 Warnings。
- Report 輸出：Estimate 只會自動產生 log；Report 必須由使用者按「輸出報表」後，選擇格式與輸出資料夾才會寫入。
- Tools 頁：整合 feed 正規化、benchmark NC 產生、Phase 2 profile 校正。
- Blocks / Charts 頁：查看 block 明細、XY toolpath、block time 與 Phase 2 速度曲線。

## Web UI 使用

```powershell
python -m nc_time_twin.web.server --host 127.0.0.1 --port 8000
```

或安裝 package 後：

```powershell
nc-time-twin-web --host 127.0.0.1 --port 8000
```

Web UI 提供原始 NC 與優化後 NC 上傳、逐段差異分析，以及 Excel / HTML / JSON / CSV 報表下載。

## 輸出

CLI：

- 指定 `--out` 可輸出 `json`、`csv`、`xlsx`、`html`。
- 每次 `estimate` 仍會自動產生：
  - `output/Report_<NC檔名>_<yyyyMMdd_HHmm>.xlsx`
  - `logs/<NC檔名>_<yyyyMMdd_HHmm>.log`

GUI：

- Estimate 後只自動產生：
  - `logs/<NC檔名>_<yyyyMMdd_HHmm>.log`
- Report 由使用者手動輸出，可選格式與輸出資料夾，預設資料夾為 `output/`。

Web UI：

- 比較報表寫入 `output/web_reports/<run_id>/`。
- Excel 報表包含 `comparison_segments` 工作表，列出原始 F、優化後 F、有效 feed、原始時間、優化後時間、時間差與異常旗標。

## 文件

- [專案介紹報告](docs/專案介紹報告.md)
- [使用者手冊](docs/使用者手冊.md)
- [系統架構](docs/系統架構.md)
- [參數設定說明](docs/參數設定說明.md)

## 測試

```powershell
pytest
```
