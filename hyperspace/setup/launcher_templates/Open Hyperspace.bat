@echo off
rem Hyperspace -- double-click this file to open the console again.
rem
rem Starts the door and opens your browser; close this window to stop it.
rem This file lives in .hyperspace\, written by the hyperspace-setup skill;
rem the isolated environment it runs is provisioned alongside it, never the
rem system Python. A Windows venv keeps its programs in Scripts\, not bin/.
cd /d "%~dp0.."
if not exist ".hyperspace\env\Scripts\hyperspace.exe" (
    echo Hyperspace: .hyperspace\env\Scripts\hyperspace.exe is missing.
    echo Run the hyperspace-setup skill in Claude Code for this project, then open this file again.
    pause
    exit /b 1
)
".hyperspace\env\Scripts\hyperspace.exe" serve --open
if errorlevel 1 pause
