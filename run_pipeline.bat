@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Samsung Price Tracker and Alert Pipeline
echo ===============================================================
echo Samsung Product Intelligence, Scraping ^& Alert Pipeline
echo ===============================================================

set PYTHON_EXEC="C:\Users\niraj\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe"
if not exist %PYTHON_EXEC% (
    set PYTHON_EXEC=python
)

if "%~1"=="" (
    echo No parameters passed. Running Alert Engine and Database Check...
    %PYTHON_EXEC% -m src.pipeline --alerts
) else (
    echo Running: %PYTHON_EXEC% -m src.pipeline %*
    %PYTHON_EXEC% -m src.pipeline %*
)

echo.
echo Pipeline execution completed.
if "%~1"=="" pause
