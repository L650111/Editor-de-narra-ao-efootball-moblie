@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
py -3.12 -c "import sys" >nul 2>&1
if errorlevel 1 goto missing
py -3.12 -m venv .venv
if errorlevel 1 goto failed
:run
.venv\Scripts\python.exe -c "import cricodecs, imageio_ffmpeg" >nul 2>&1
if not errorlevel 1 goto launch
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
:launch
.venv\Scripts\python.exe iniciar.py %*
if errorlevel 1 goto failed
exit /b 0
:missing
echo Instale Python 3.12 de 64 bits com o Python Launcher e Tkinter.
echo Site oficial: https://www.python.org/downloads/
echo Depois abra este arquivo novamente.
pause
exit /b 1
:failed
echo.
echo O programa encontrou um erro. Leia as mensagens acima.
pause
exit /b 1
