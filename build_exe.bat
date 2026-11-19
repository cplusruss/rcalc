@echo off
cd /d "%~dp0"
rem the build tree lives outside Dropbox: its sync locks the thousands of files PyInstaller writes and rewrites
if not defined OUT set OUT=C:\tmp\rcalc-build
if not defined PY set PY=C:\Python\313\python.exe
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name rcalc ^
 --icon "%~dp0Rcalc.ico" ^
 --workpath "%OUT%\work" --distpath "%OUT%\dist" --specpath "%OUT%" ^
 --add-data "%~dp0Rcalc.ico;." ^
 --add-data "%~dp0resource\periodic_data.py;resource" ^
 --add-data "%~dp0resource\mechanical_data.py;resource" ^
 --add-data "%~dp0resource\ICs;resource\ICs" ^
 --collect-data skrf ^
 --exclude-module tkinter --exclude-module pytest ^
 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 ^
 --exclude-module setuptools --exclude-module pkg_resources --exclude-module IPython ^
 "%~dp0rcalc.py" || exit /b 1
if not exist dist mkdir dist || exit /b 1
rem never rcalc.exe in the root: Rcalc.exe there is the pylauncher launcher
move /y "%OUT%\dist\rcalc.exe" dist\rcalc.exe || exit /b 1
