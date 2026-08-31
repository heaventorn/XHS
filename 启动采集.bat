@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   小红书关键词采集工具（双击运行）
echo ============================================================
echo.

REM ===== 双密码验证（访问密码 + 本地pwd.key二级密钥）=====
set "PY=C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" goto nopy
"%PY%" auth_check.py
if errorlevel 1 (
    echo [!] 密码验证失败或已取消，程序退出。
    pause
    exit /b 1
)
echo [√] 双密码验证通过，开始运行...
echo.

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
