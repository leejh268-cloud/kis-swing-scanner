@echo off
setlocal

cd /d "%~dp0"

echo ===================================
echo  KIS Scanner - Auto Scan and Push
echo  %date% %time%
echo ===================================

if not exist ".venv" (
    echo [ERROR] Virtual environment not found. Run run_test_windows.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

if "%KIS_APP_KEY%"=="" (
    echo [ERROR] KIS_APP_KEY not set. See instructions below.
    echo This script needs KIS_APP_KEY and KIS_APP_SECRET set as permanent
    echo Windows environment variables ^(not just for one PowerShell session^).
    exit /b 1
)

echo [1/2] Running swing scan...
python -m scanner.run_swing
if errorlevel 1 (
    echo [ERROR] Swing scan failed. See output above.
    exit /b 1
)

echo [2/2] Pushing results to GitHub...
git add docs\data\swing_results.json
git commit -m "chore: auto scan update %date% %time%"
git push

echo Done.
