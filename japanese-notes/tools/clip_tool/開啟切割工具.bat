@echo off
chcp 65001 >nul
rem 用法：把這個檔案和 clip_tool.py 放在音檔、切點表所在的資料夾，雙擊即可。
where python >nul 2>nul
if errorlevel 1 (
  echo 找不到 Python。請先到 https://www.python.org/downloads/ 安裝（安裝時勾選 Add python.exe to PATH）。
  pause
  exit /b 1
)
python "%~dp0clip_tool.py" "%cd%"
pause
