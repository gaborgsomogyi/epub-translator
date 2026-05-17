@echo off
echo Setting up Python 3.13 virtual environment...

py -3.13 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.13 not found. Installing via py manager...
    py install 3.13
    if errorlevel 1 (
        echo Failed to install Python 3.13. Please install it manually.
        exit /b 1
    )
)

py -3.13 -m venv .venv
if errorlevel 1 (
    echo Failed to create virtual environment.
    exit /b 1
)

call .venv\Scripts\activate.bat
pip install -e .

echo.
echo Done! Virtual environment is ready and activated.
echo To activate it in a new terminal, run: .venv\Scripts\activate
