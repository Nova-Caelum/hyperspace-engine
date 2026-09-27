@echo off
rem Hyperspace -- double-click this file to open the console again.
rem
rem Starts the door and opens your browser; close this window to stop it.
rem This file lives in .hyperspace\, written by the hyperspace-setup skill;
rem the isolated environment it execs is provisioned alongside it, never the
rem system Python.
rem
rem Untested on Windows at authoring time (out of scope for this row) -- the
rem venv layout there is Scripts\ rather than bin/, reflected below.
cd /d "%~dp0.."
".hyperspace\env\Scripts\hyperspace.exe" serve --open
