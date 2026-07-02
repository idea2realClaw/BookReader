@echo off
chcp 65001
echo ==============================
echo BookReader 桌面模式启动脚本
echo ==============================
echo.

cd D:\DiskD\GitHub\BookReader

echo 正在启动桌面应用...
echo.
echo 提示: 关闭应用窗口来停止程序
echo.

.venv\Scripts\python.exe main.py --mode desktop

pause
