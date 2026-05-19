@echo off
chcp 65001 >nul 2>&1
title 龙瞳Pro - A股智能投研平台

echo.
echo  🐉 龙瞳Pro 启动中...
echo.

set PYTHON=C:\Users\lilv\.workbuddy\binaries\python\envs\tradingagents\Scripts\python.exe
set APP_DIR=D:\AI-Tools\TradingAgents\dragon_eye

"%PYTHON%" -m streamlit run "%APP_DIR%\app.py" --server.port 8501 --server.headless true

pause
