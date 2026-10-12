@echo off
rem bin\hyperspace-env.cmd - how Claude Code starts this plugin's MCP server on
rem Windows. `.mcp.json` names bin/hyperspace-env with no extension; Windows
rem finds this file beside it.
rem
rem The server lives in the project's .hyperspace\env, and a downloaded folder
rem can ship a file there. So this script never starts anything in the project
rem itself: it finds this computer's own Python and hands over to
rem hyperspace\provenance.py, which starts the project's environment only when
rem setup built it and recorded it on this computer. Every Python it tries is
rem run once, quietly, before it is trusted, so the Microsoft Store placeholder
rem (which only prints an install prompt) is passed over. -I keeps that Python
rem from reading the project's folder or environment variables on its way in.

setlocal
set "PY="
for %%V in (13 12 11) do if exist "%USERPROFILE%\.local\bin\python3.%%V.exe" call :try "%USERPROFILE%\.local\bin\python3.%%V.exe"
call :try py -3
call :try python3
call :try python
if not defined PY goto :none

%PY% -I "%~dp0..\hyperspace\provenance.py" run -- %*
exit /b %ERRORLEVEL%

:none
echo Hyperspace could not find Python on this computer, so its server did not start. Install Python 3.11 or newer, then run the hyperspace-setup skill. 1>&2
exit /b 1

rem Sets PY to the command in its arguments when that command runs Python.
:try
if defined PY exit /b 0
%* -I -S -c "" <nul >nul 2>&1 || exit /b 0
set PY=%*
exit /b 0
