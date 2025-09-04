@echo off
echo Starting Django Application...
echo.

REM Ensure the script runs from its own directory
cd /D "%~dp0"

echo Activating virtual environment...
call .\venv\Scripts\activate.bat

IF "%VIRTUAL_ENV%"=="" (
    echo ERROR: Virtual environment could not be activated.
    echo Please ensure the 'venv' folder exists in this directory.
    pause
    exit /b 1
)

echo Virtual environment activated.
echo.

REM --- Launch the browser ---
echo Launching web browser to http://localhost:8002/dashboard
REM The empty "" after start is a best practice; it acts as a dummy title.
start "" "http://localhost:8002/dashboard"

REM As an alternative, you can use explorer if the 'start' command fails.
REM To do so, comment out the 'start' line above and uncomment the line below.
REM explorer "http://localhost:8002/dashboard"

echo.
echo Launching Django server...
echo (This window will show server logs. Press Ctrl+C to stop the server.)
echo.

REM *** CRITICAL: EDIT THE LINE BELOW WITH YOUR ACTUAL PROJECT FOLDER NAME ***
waitress-serve --host 127.0.0.1 --port=8002 mcms_project.wsgi:application
REM **********************************************************************

echo.
echo Server has stopped.
pause