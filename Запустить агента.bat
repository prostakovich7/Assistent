@echo off
chcp 65001 >nul
title Ассистент руководителя
cd /d "%~dp0"
echo Агент запущен. Не закрывайте это окно, пока нужен бот.
".venv\Scripts\python.exe" -m agent
pause
