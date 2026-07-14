@echo off
cd /d "D:\AI\autoTest"

:: 直接启动 GUI，不显示 CMD 窗口
start "" pythonw desktop_app.py

:: 如果 pythonw 不可用，回退到 python + 隐藏窗口
if errorlevel 1 (
    start "" /b python desktop_app.py
)
