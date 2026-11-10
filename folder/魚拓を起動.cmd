@echo off
cd /d "%~dp0"
python -c "import playwright" >nul 2>&1
if errorlevel 1 (
  python -m pip install playwright
  if errorlevel 1 (
    echo Failed to install Playwright. Please check Python and your connection.
    pause
    exit /b 1
  )
)
python archive_server.py
if errorlevel 1 pause
