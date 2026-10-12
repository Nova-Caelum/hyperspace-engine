@echo off
rem bin\hyperspace-env.cmd - how Claude Code starts this plugin's MCP server on
rem Windows. `.mcp.json` names bin/hyperspace-env with no extension; Windows
rem finds this file beside it.
rem
rem The server lives in the project's .hyperspace\env, and a downloaded folder
rem can ship a file there. So this script never starts anything in the project
rem itself: it finds this computer's own Python and hands over to
rem hyperspace\provenance.py, which starts the project's environment only when
rem setup built it and recorded it on this computer. Each Python is found by
rem its full path, never by a bare name (a bare name would also find a program
rem in the current folder, which is the project), and one that lives inside
rem the project is passed over. Every other one is run once, quietly, before
rem it is trusted, so the Microsoft Store placeholder (which only prints an
rem install prompt) is passed over too. -I keeps that Python from reading the
rem project's folder or environment variables on its way in.

setlocal EnableExtensions DisableDelayedExpansion
set "NC_PROJECT=%CLAUDE_PROJECT_DIR%"
if not defined NC_PROJECT set "NC_PROJECT=%CD%"
set "NC_PROJECT=%NC_PROJECT:/=\%"
if "%NC_PROJECT:~-1%"=="\" set "NC_PROJECT=%NC_PROJECT:~0,-1%"
set "NC_PY="

for %%V in (13 12 11) do if not defined NC_PY call :try "%USERPROFILE%\.local\bin\python3.%%V.exe"
for %%N in (py.exe) do if not defined NC_PY if not "%%~$PATH:N"=="" call :try "%%~$PATH:N" -3
for %%N in (python3.exe python.exe) do if not defined NC_PY if not "%%~$PATH:N"=="" call :try "%%~$PATH:N"

if not defined NC_PY goto none
%NC_PY% -I "%~dp0..\hyperspace\provenance.py" run -- %*
exit /b %errorlevel%

:none
echo Hyperspace could not find Python on this computer, so its server did not start. Install Python 3.11 or newer, then run the hyperspace-setup skill. 1>&2
exit /b 1

rem The first argument is a Python (the second, -3, is for the py launcher).
rem It is used when it is a file outside the project and it starts.
:try
set "NC_CANDIDATE=%~1"
if not exist "%NC_CANDIDATE%" exit /b 0
call set "NC_REST=%%NC_CANDIDATE:*%NC_PROJECT%\=%%"
if not "%NC_REST%"=="%NC_CANDIDATE%" exit /b 0
"%NC_CANDIDATE%" %~2 -I -S -c "" <nul >nul 2>&1
if not "%errorlevel%"=="0" exit /b 0
set NC_PY="%NC_CANDIDATE%" %~2
exit /b 0
