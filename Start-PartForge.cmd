@echo off
rem PartForge starten.
rem  * Programmpaket: startet PartForge.exe neben dieser Datei.
rem  * Quellcode: scripts\bootstrap.py prueft bei jedem Start die Python-Umgebung (.venv) und die
rem    Oberflaeche, richtet sie bei Bedarf ein bzw. baut sie neu und startet dann PartForge.
rem    Python wird nur verwendet, wenn es wirklich startet und mindestens Version 3.11 hat
rem    (der Platzhalter "python.exe" des Microsoft Store wird so uebersprungen).
setlocal EnableExtensions
cd /d "%~dp0"

if exist "%~dp0PartForge.exe" (
  start "" "%~dp0PartForge.exe" %*
  exit /b 0
)

set "PF_VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%PF_VENV_PY%" (
  "%PF_VENV_PY%" -c "import sys" >nul 2>nul
  if not errorlevel 1 goto run_venv
  echo Die Python-Umgebung .venv startet nicht mehr und wird neu eingerichtet.
)

call :find_python
if not defined PF_PY goto no_python
%PF_PY% "%~dp0scripts\bootstrap.py" %*
if errorlevel 1 goto failure
exit /b 0

:run_venv
"%PF_VENV_PY%" "%~dp0scripts\bootstrap.py" %*
if errorlevel 1 goto failure
exit /b 0

:find_python
rem Bevorzugt die getestete Version 3.13, dann jede andere ab 3.11.
set "PF_PY="
set "PF_OLD="
where py >nul 2>nul
if errorlevel 1 goto find_python_path
call :try_python py -3.13
if defined PF_PY goto :eof
call :try_python py -3
if defined PF_PY goto :eof
:find_python_path
for /f "delims=" %%P in ('where python 2^>nul') do (
  call :try_python "%%P"
  if defined PF_PY goto :eof
)
goto :eof

:try_python
rem Exit-Code 0 = brauchbar, 1 = zu alt, sonst (z. B. 9009) = kein echtes Python.
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 2 goto :eof
if errorlevel 1 (
  set "PF_OLD=1"
  goto :eof
)
set PF_PY=%*
goto :eof

:no_python
echo.
if defined PF_OLD (
  echo Gefunden wurde nur eine zu alte Python-Version - PartForge braucht Python 3.11 oder neuer.
) else (
  echo Python 3.11 oder neuer wurde nicht gefunden.
)
echo.
echo So geht es weiter:
echo   1. Python 3.13 von https://www.python.org/downloads/windows/ installieren
echo      und im Installer "Add python.exe to PATH" ankreuzen.
echo   2. Start-PartForge.cmd erneut starten. Die erste Einrichtung dauert einige Minuten
echo      und braucht eine Internetverbindung.
echo Oder das fertige Programmpaket verwenden: PartForge.exe braucht weder Python noch Node.js.
if exist "%~dp0dist\PartForge\PartForge.exe" echo Ein gebautes Programmpaket liegt unter dist\PartForge\PartForge.exe.
goto failure_end

:failure
echo.
echo Hilfe:
echo  - Python 3.11 oder neuer: https://www.python.org/downloads/windows/
echo    (beim Installieren "Add python.exe to PATH" ankreuzen)
echo  - Oder das fertige Programmpaket verwenden: PartForge.exe braucht weder Python noch Node.js.

:failure_end
echo.
echo PartForge konnte nicht gestartet werden - siehe Meldung oben.
pause
exit /b 1
