@echo off
chcp 936 >nul 2>&1
title TradingAgents CLI
color 0A

set HTTP_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=http://127.0.0.1:7897

cd /d "D:\AI-Tools\TradingAgents"
"C:\Users\lilv\.workbuddy\binaries\python\envs\tradingagents\Scripts\tradingagents.exe" %*

pause
