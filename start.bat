@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting server...
start "" "http://localhost:8765/index.html"
python server.py
pause
