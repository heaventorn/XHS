@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   大爬虫框架 · 多渠道找 CFO/融资负责人（双击运行）
echo ============================================================
echo.

REM ===== 双密码验证（访问密码 + 本地 pwd.key 二级密钥）=====
set "PY=C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" goto nopy
"%PY%" run.py
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
