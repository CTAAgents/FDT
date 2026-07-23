@echo off
REM Loop Runner for FDC Data Injection Verification
REM Runs verification every 5 minutes, max 30 rounds

cd /d d:\Programs\FDT
set MAX=30
set INTERVAL=300

for /l %%i in (1,1,%MAX%) do (
    echo --- Round %%i/%MAX% ---
    python memory\loop_fdc_driver.py
    if !ERRORLEVEL! equ 0 (
        echo ✅ FDC Data Injection verification passed
        exit /b 0
    )
    python -c "import json; s=json.load(open('memory/loop_state.json')); exit(0 if s.get('status') in ('stalled','max_rounds','completed') else 1)" 2>nul
    if !ERRORLEVEL! equ 0 (
        echo ⏹ Loop terminated by state
        exit /b 0
    )
    echo Sleeping %INTERVAL% seconds...
    timeout /t %INTERVAL% /nobreak >nul
)
echo ⏹ Max rounds reached
exit /b 1
