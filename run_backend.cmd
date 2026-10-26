@echo off
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Create the environment first:
  echo   py -3.12 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
"%PYTHON%" "%~dp0run_backend.py" %*
exit /b %errorlevel%
