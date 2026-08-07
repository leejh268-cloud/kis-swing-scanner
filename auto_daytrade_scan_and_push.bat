@echo off
setlocal

cd /d "%~dp0"

echo ===================================
echo  KIS Scanner - Auto Daytrade Scan and Push
echo  %date% %time%
echo ===================================

if not exist ".venv" (
    echo [ERROR] Virtual environment not found. Run run_test_windows.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

if "%KIS_APP_KEY%"=="" (
    echo [ERROR] KIS_APP_KEY not set as a permanent environment variable.
    exit /b 1
)

echo [1/2] Running daytrade scan...
python -m scanner.run_daytrade
if errorlevel 1 (
    echo [ERROR] Daytrade scan failed. See output above.
    exit /b 1
)

echo [2/2] Pushing results to GitHub...
git add docs\data\daytrade_results.json
git commit -m "chore: auto daytrade scan update %date% %time%"
git push

echo Done.
