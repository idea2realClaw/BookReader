@echo off
chcp 65001 > nul
echo ===============================
echo BookReader 启动脚本
echo ===============================
echo.

REM 杀死占用端口的进程
echo [1/3] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8551') do (
    taskkill /f /pid %%a >nul 2>&1
)

REM 等待一下
timeout /t 2 > nul

echo [2/3] 启动 BookReader (浏览器模式)...
echo.
echo 应用将在浏览器中打开: http://127.0.0.1:8552
echo 按 Ctrl+C 停止服务器
echo.

cd /d D:\DiskD\GitHub\BookReader
.venv\Scripts\python main.py --mode browser --port 8552

pause
