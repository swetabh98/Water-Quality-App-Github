@echo off
title Water Quality App Launcher

:: 1. Navigate to the project directory
:: /d ensures we switch drives (C: to D:) and directory in one command
cd /d "D:\water_quality_app"

:: 2. Create virtual environment if it's missing
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: 3. Activate the virtual environment
:: We use 'call' so the script continues after activation
call venv\Scripts\activate.bat

:: 4. Run the WSGI server
echo Starting Waitress server...
python wsgi.py

:: 5. Keep the window open so you can see errors if it closes unexpectedly
pause