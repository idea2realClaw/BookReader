@echo off
chcp 65001 > nul
echo ==============================
echo BookReader 桌面模式启动脚本
echo ==============================
echo.

cd /d D:\DiskD\GitHub\BookReader

echo 正在启动桌面应用...
echo.
echo 提示: 关闭此窗口不会停止应用，请在应用窗口中按 X 关闭
echo.

.venv\Scripts\python main.py --mode desktop

pause
