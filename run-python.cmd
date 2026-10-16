@echo off
rem Roda um Python 3 instalado na maquina. Uso: run-python.cmd [python|pythonw] script.py [args]
rem Ordem de busca: variavel CLAUDE_WIDGET_PYTHON (caminho do python.exe) -> launcher "py -3"
rem -> python no PATH -> Python do QGIS mais recente. Com pythonw (o widget) so aceita um
rem Python que consiga importar o PyQt5; a statusline (python) usa so a biblioteca padrao.
setlocal
set "EXE=%~1"
shift
set "NEED_QT="
if /i "%EXE%"=="pythonw" set "NEED_QT=1"
set "PYTHONUTF8=1"

if defined CLAUDE_WIDGET_PYTHON call :try "%CLAUDE_WIDGET_PYTHON%" && goto run
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do call :try "%%P" && goto run
for /f "delims=" %%P in ('where python 2^>nul') do call :try "%%P" && goto run
call :qgis && goto run
if defined NEED_QT (
  echo Nenhum Python com PyQt5 encontrado. Instale o Python 3.8+ e rode: py -m pip install PyQt5 1>&2
) else (
  echo Nenhum Python 3 encontrado. Instale pelo python.org ou defina CLAUDE_WIDGET_PYTHON. 1>&2
)
exit /b 1

:run
"%PYDIR%%EXE%.exe" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

rem Aceita o python.exe em %1 se ele roda (o atalho da Microsoft Store sem Python instalado
rem falha aqui) e, quando preciso, se importa o PyQt5. Guarda a pasta dele em PYDIR.
:try
if not exist "%~1" exit /b 1
"%~1" -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 || exit /b 1
if defined NEED_QT ("%~1" -c "import PyQt5.QtWidgets" >nul 2>&1 || exit /b 1)
set "PYDIR=%~dp1"
exit /b 0

rem Python do QGIS: precisa das DLLs do QGIS e do Qt no PATH.
:qgis
set "QGIS="
for /f "delims=" %%D in ('dir /b /ad /o:n "C:\Program Files\QGIS *" 2^>nul') do set "QGIS=C:\Program Files\%%D"
if not defined QGIS exit /b 1
set "PATH=%QGIS%\bin;%QGIS%\apps\Qt5\bin;%PATH%"
set "QT_PLUGIN_PATH=%QGIS%\apps\Qt5\plugins"
for /d %%V in ("%QGIS%\apps\Python3*") do call :try "%%V\python.exe" && exit /b 0
exit /b 1
