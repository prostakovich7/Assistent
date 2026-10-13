@echo off
chcp 65001 >nul
title Пример отчёта
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -m agent.demo
start "" "reports\пример\полный.md"
echo.
echo Чтобы узнать подробности, впишите фамилию, отдел, улицу или номер задачи
echo (например: Соколов, абонентский, Тореза, T-105). Пустая строка - выход.
:ask
echo.
set "Q="
set /p "Q=Подробнее про: "
if "%Q%"=="" goto :eof
".venv\Scripts\python.exe" -X utf8 -m agent.demo %Q%
goto ask
