@echo off
chcp 65001 >nul 2>&1
title TradingAgents - DeepSeek
color 0A

echo.
echo  ========================================
echo   TradingAgents - DeepSeek Chat
echo  ========================================
echo.
echo  Usage: run_deepseek.bat [TICKER] [DATE]
echo  Example: run_deepseek.bat AAPL 2026-05-09
echo  Example: run_deepseek.bat NVDA
echo  Default: NVDA today
echo.

cd /d "D:\AI-Tools\TradingAgents"
python run_deepseek.py %1 %2

echo.
pause
