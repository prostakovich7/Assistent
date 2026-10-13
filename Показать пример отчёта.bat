@echo off
chcp 65001 >nul
title Пример отчёта
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: устанавливаю нужное для демо, это 1-2 минуты...
  python -m venv .venv
  if errorlevel 1 (
    echo Не найден Python. Установите Python 3.11 или новее с python.org и запустите снова.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements-demo.txt
)
".venv\Scripts\python.exe" -X utf8 -m agent.demo
start "" notepad "reports\пример\полный.md"
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
