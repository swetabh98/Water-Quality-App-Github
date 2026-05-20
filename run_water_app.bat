@echo off
TITLE Water Quality App - Production Server
COLOR 0B

:: 1. Navigate to the project directory
D:
cd "D:\Swetabh\water_quality_app"

:: 2. Activate the virtual environment
echo [1/3] Activating Virtual Environment...
call venv\Scripts\activate

:: 3. Upgrade pip and install missing runtime packages
echo [2/3] Checking for optimizations...
python -m pip install --upgrade pip --quiet --no-cache-dir
python -m pip install flask-compress whitenoise psycopg2-binary --quiet --no-cache-dir

:: 4. Launch the Browser
echo [3/3] Starting Server and Opening Browser...
start "" "http://localhost:8826"

:: 5. Run the production server
echo.
echo Server is running! Close this window to stop the app.
python wsgi.py

pause
