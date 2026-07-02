@echo off
chcp 65001 > nul
echo ==============================
echo BookReader 浏览器模式启动脚本
echo ==============================
echo.

REM 设置工作目录
cd /d D:\DiskD\GitHub\BookReader

REM 清理旧进程（如果有）
echo [1/3] 清理旧进程...
for /f "tokens=5" %%%a in ('netstat -ano ^| findstr :8550') do (
    taskkill /f /pid %%%a >nul 2>&1
)
timeout /t 2 > nul

echo [2/3] 启动 BookReader (浏览器模式)...
echo.
echo 应用将在浏览器中打开: http://127.0.0.1:8550
echo 按 Ctrl+C 停止服务器
echo.

REM 激活虚拟环境并运行
call .venv\Scripts\activate.bat
python main.py --mode browser --port 8550

pause
