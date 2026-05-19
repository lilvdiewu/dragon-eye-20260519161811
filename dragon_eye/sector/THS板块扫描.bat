@echo off
chcp 65001 >nul
cd /d "%~dp0"
python ths_sector_scanner.py %*
pause
