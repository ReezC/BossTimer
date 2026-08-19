@echo off
chcp 65001 >nul
echo ============================================
echo   BossTimer 一键打包脚本
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] 正在使用 PyInstaller 打包...
python -m PyInstaller --onefile --noconsole --clean --name BossTimer main.py
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查上方错误信息。
    pause
    exit /b 1
)
echo.

echo [2/3] 清理无用中间文件...
if exist build rmdir /s /q build
if exist __pycache__ rmdir /s /q __pycache__
echo.

echo [3/3] 完成！
echo 输出文件: %~dp0dist\BossTimer.exe
echo.
echo 提示：数据文件需与 exe 同级，放在 dist\data\ 目录下。
echo.
pause
