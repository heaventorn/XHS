@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   小红书关键词采集工具（双击运行）
echo ============================================================
echo.

REM ===== 密码验证 =====
set "CORRECT_PWD=0762"
set "INPUT_PWD="
for /f "delims=" %%i in ('powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.Interaction]::InputBox('请输入访问密码','身份验证','')"') do set "INPUT_PWD=%%i"

if not defined INPUT_PWD (
    echo [!] 未输入密码或已点取消，程序退出。
    pause
    exit /b 1
)

if "%INPUT_PWD%"=="%CORRECT_PWD%" (
    echo [√] 密码验证通过，开始运行...
    echo.
) else (
    echo [!] 密码错误，程序退出。
    pause
    exit /b 1
)

set "PY=C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" goto nopy
"%PY%" xhs_keyword_scraper.py
goto done
:nopy
echo [!] 未找到 Python 3.11：%PY%
echo     请确认已安装 Python 3.11
:done
echo.
echo ============================================================
echo   运行结束，按任意键关闭窗口
echo ============================================================
pause
