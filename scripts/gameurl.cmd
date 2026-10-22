@echo off
setlocal

set "PROJECT_DIR=%~dp0.."
set "SERVER_SCRIPT=%PROJECT_DIR%\src\web_input_server.py"

where py >nul 2>nul
if errorlevel 1 goto check_python
py -3 --version >nul 2>nul
if not errorlevel 1 goto use_py

:check_python
where python >nul 2>nul
if not errorlevel 1 goto use_python

echo Python 3 was not found. Install Python 3 and try again.
exit /b 1

:use_py
py -3 "%SERVER_SCRIPT%" %*
exit /b %errorlevel%

:use_python
python "%SERVER_SCRIPT%" %*
exit /b %errorlevel%
