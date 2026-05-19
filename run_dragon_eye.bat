@echo off
chcp 936 >nul 2>&1
title DragonEye Pro
color 0B

cd /d "D:\AI-Tools\TradingAgents"
set PYTHONPATH=D:\AI-Tools\TradingAgents
"C:\Users\lilv\.workbuddy\binaries\python\envs\tradingagents\Scripts\streamlit.exe" run dragon_eye/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false

pause
