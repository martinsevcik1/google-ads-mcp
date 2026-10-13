@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Instalace Google Ads MCP
echo.
echo   Instalace Google Ads MCP
echo   ------------------------------
echo.
set "PYEXE="
set "PYARG="

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel%==0 ( set "PYEXE=py" & set "PYARG=-3" & goto run )
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel%==0 ( set "PYEXE=python" & goto run )
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ( set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto run )

echo Python 3.10 nebo novejsi nebyl nalezen. Zkusim ho nainstalovat (par minut)...
echo.
where winget >nul 2>&1 || goto nopy
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ( set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto run )

:nopy
echo.
echo Python se nepodarilo nainstalovat automaticky.
echo Otevru stranku ke stazeni. Pri instalaci zaskrtni "Add python.exe to PATH",
echo pak tento soubor spust znovu.
start "" "https://www.python.org/downloads/"
echo.
pause
exit /b 1

:run
"%PYEXE%" %PYARG% install.py
echo.
pause
