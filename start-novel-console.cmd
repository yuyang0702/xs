@echo off
setlocal
set PYTHONUTF8=1
set NOVEL_FLYWHEEL_DATA_DIR=%~dp0data
"%~dp0.venv\Scripts\python.exe" -m novel_flywheel.launcher
endlocal
