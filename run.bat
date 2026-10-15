@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py fetch_news.py %*) else (python fetch_news.py %*)
echo.
echo Готово. Откройте файл candidates.md в этой папке.
pause
