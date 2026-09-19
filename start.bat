@echo off
REM start.bat -- thin wrapper around start.py.  See start.py --help.
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if %errorlevel%==0 (
    python start.py %*
    exit /b %errorlevel%
)
where py >nul 2>&1
if %errorlevel%==0 (
    py start.py %*
    exit /b %errorlevel%
)
echo python not found in PATH
exit /b 1
