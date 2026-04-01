@echo off
setlocal

REM Check if virtual environment exists
IF NOT EXIST "venv" (
    echo Virtual environment not found. Creating one...
    python -m venv venv
) ELSE (
    echo Virtual environment found.
)

REM Activate the virtual environment
call venv\Scripts\activate

REM Check if requirements.txt exists
IF EXIST "requirements.txt" (
    echo Installing required dependencies...
    pip install -r requirements.txt
) ELSE (
    echo No requirements.txt found. Skipping installation.
)

REM Run the Python script
echo Running Civitai_Image_API.py...
python Civitai_Image_API.py

REM Deactivate the virtual environment
deactivate

endlocal
