@echo off
REM Windows 启动脚本 - 使用 .venv 虚拟环境运行 BookReader

set SCRIPT_DIR=%~dp0
"%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%main.py" %*
