@echo off
chcp 65001 >nul
rem 只讀取電腦環境，不安裝、不修改任何東西。結果存在 inventory.txt。
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0inventory.ps1"
pause
