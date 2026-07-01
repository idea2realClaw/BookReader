# PowerShell startup script - Run BookReader with .venv virtual environment

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\.venv\Scripts\python.exe" "$ScriptDir\main.py" @args
