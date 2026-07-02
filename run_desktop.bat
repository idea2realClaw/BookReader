@echo off
chcp 65001 > nul
echo ==============================
echo BookReader 桌面模式启动脚本
echo ==============================
echo.

REM 设置工作目录
cd /d D:\DiskD\GitHub\BookReader

echo 正在启动桌面应用...
echo.
echo 提示: 关闭应用窗口来停止程序
echo.

REM 激活虚拟环境并运行
call .venv\Scripts\activate.bat
python main.py --mode desktop

pause
