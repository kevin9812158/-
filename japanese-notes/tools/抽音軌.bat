@echo off
chcp 65001 >nul
setlocal
rem 用法：把影片檔拖到這個檔案上（可一次拖多個），會在影片旁邊產生同名的 .m4a 音軌。
rem 單聲道 96kbps，一小時約 43MB，符合 Plaud 500MB 上限。需要先安裝 ffmpeg：winget install Gyan.FFmpeg

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo 找不到 ffmpeg。請先在終端機執行：winget install Gyan.FFmpeg
  echo 安裝完要重新開一次檔案總管或重新開機，再拖一次。
  pause
  exit /b 1
)

if "%~1"=="" (
  echo 請把影片檔拖到這個檔案上。
  pause
  exit /b 1
)

:next
if "%~1"=="" goto done
echo.
echo 處理中：%~nx1
ffmpeg -hide_banner -loglevel error -stats -y -i "%~1" -vn -ac 1 -c:a aac -b:a 96k "%~dpn1.m4a"
if errorlevel 1 (
  echo 失敗：%~nx1
) else (
  for %%F in ("%~dpn1.m4a") do (
    set /a MB=%%~zF/1048576
    call echo 完成：%%~nxF（%%MB%% MB）
    if %%~zF GTR 524288000 echo 注意：超過 500MB，Plaud 可能不收。
  )
)
shift
goto next

:done
echo.
echo 全部完成。
pause
