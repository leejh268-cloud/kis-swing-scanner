@echo off
setlocal

echo ===================================
echo  KIS Scanner - Setup and Test
echo ===================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Install it from https://python.org/downloads
    echo IMPORTANT: check "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
) else (
    echo [1/4] Virtual environment already exists. Skipping.
)

echo [2/4] Installing required libraries... this may take a minute
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

if "%KIS_APP_KEY%"=="" (
    echo.
    echo [3/4] Enter your Korea Investment ^& Securities API keys.
    set /p KIS_APP_KEY=App Key: 
    set /p KIS_APP_SECRET=App Secret: 
) else (
    echo [3/4] KIS_APP_KEY already set in environment. Skipping.
)

echo.
echo [4/4] Running connection test...
echo -----------------------------------
python -m scanner.test_connection
echo -----------------------------------
echo.
echo Done. Please check the output above.
echo If there was an error, copy everything in this window and share it.
pause
