# NC-Code 加工時間估測器

第一階段實作目標是把 NC-Code 解析、模態狀態、IR 中介模型、幾何路徑與時間估算串成可用工具。

## CLI

```powershell
python -m nc_time_twin estimate --nc examples/basic.nc --profile profiles/default_3axis.yaml --out result.json
```

若未安裝成套件，可先設定：

```powershell
$env:PYTHONPATH="src"
python -m nc_time_twin estimate --nc examples/basic.nc --profile profiles/default_3axis.yaml --out result.json
```

## GUI

```powershell
python -m nc_time_twin.gui.main_window
```

GUI 需要 `PySide6`。核心 CLI 與測試不依賴 GUI 啟動。

## 支援範圍

- G-code: `G00/G01/G02/G03/G04/G17/G18/G19/G20/G21/G80/G81/G82/G83/G90/G91/G93/G94/G95`
- M-code: `M03/M04/M05/M06/M08/M09/M30`
- 圓弧: IJK 與 R 近似解析
- 固定循環: G81/G82/G83 展開成 IR blocks
- 報告: CSV、JSON、Excel、HTML
