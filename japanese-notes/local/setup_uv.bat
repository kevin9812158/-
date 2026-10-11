@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 用 uv 建立本專案的獨立環境（.venv）。不會安裝或修改系統的 Python、ffmpeg 等任何東西。
where uv >nul 2>nul
if errorlevel 1 (
  echo 找不到 uv。本工具不會自動安裝，請先自行安裝 uv：
  echo   https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo 注意：找不到 ffmpeg。切割和轉檔需要它，請自行安裝後再執行（本工具不會自動安裝）。
)
echo [1/3] 建立專案環境（.venv，只在這個資料夾裡）…
uv sync
if errorlevel 1 ( echo uv sync 失敗，請把上面的訊息貼給 Claude。 & pause & exit /b 1 )
echo [2/3] 下載模型到 models\（約 750 MB，已存在會跳過）…
uv run download_models.py
if errorlevel 1 ( echo 模型下載失敗，請把上面的訊息貼給 Claude。 & pause & exit /b 1 )
echo [3/3] 檢查環境…
uv run pipeline.py check
pause
