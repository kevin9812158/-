@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 線上課音訊流程：本地環境安裝 ===
where python >nul 2>nul
if errorlevel 1 (
  echo 找不到 Python，現在用 winget 安裝…
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo Python 安裝完成。請「關閉這個視窗」，再雙擊一次 setup_windows.bat 繼續。
  pause
  exit /b 0
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo 找不到 ffmpeg，現在用 winget 安裝…
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo.
  echo ffmpeg 安裝完成。請「關閉這個視窗」，再雙擊一次 setup_windows.bat 繼續。
  pause
  exit /b 0
)
echo 安裝 Python 套件…
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 ( echo 套件安裝失敗，請把上面的訊息貼給 Claude。 & pause & exit /b 1 )
echo 下載模型（約 750 MB，只需要一次）…
python download_models.py
if errorlevel 1 ( echo 模型下載失敗，請把上面的訊息貼給 Claude。 & pause & exit /b 1 )
if not exist lessons mkdir lessons
python pipeline.py check
echo.
echo 完成。之後每一課：在 lessons 底下開一個資料夾，放入課堂音檔，再請 Claude 處理。
pause
