@echo off
setlocal EnableExtensions

rem Install Git, Python 3.12, and Node.js 22, then build the OMNE desktop simulation.
rem Paste into Command Prompt. No NVIDIA key is required.

where winget >nul 2>&1
if errorlevel 1 (
  echo winget is not available. Install "App Installer" from the Microsoft Store, then run this again.
  exit /b 1
)

echo.
echo Installing Git, Python 3.12, and Node.js 22.
echo Windows may ask for administrator approval.
echo.

call :winget_install Git.Git
call :winget_install Python.Python.3.12
call :winget_install OpenJS.NodeJS.22
call :refresh_path

where git >nul 2>&1 || (
  echo Git is not on PATH after installation. Close this window, open a new Command Prompt, and run this script again.
  exit /b 1
)
where py >nul 2>&1 || (
  echo The Python launcher is not on PATH after installation. Close this window, open a new Command Prompt, and run this script again.
  exit /b 1
)
where node >nul 2>&1 || (
  echo Node.js is not on PATH after installation. Close this window, open a new Command Prompt, and run this script again.
  exit /b 1
)
where npm >nul 2>&1 || (
  echo npm is not on PATH after installation. Close this window, open a new Command Prompt, and run this script again.
  exit /b 1
)

set "DEST=%USERPROFILE%\OmneOS"
set "BRANCH=cursor/omne-desktop-windows-92cc"
set "REPO=https://github.com/answerfirstai-ai/OmneOS.git"

if not exist "%DEST%\.git" (
  echo.
  echo Cloning %BRANCH% into %DEST%
  git clone --branch "%BRANCH%" --single-branch "%REPO%" "%DEST%"
  if errorlevel 1 exit /b 1
) else (
  echo.
  echo Updating %DEST%
  git -C "%DEST%" fetch origin "%BRANCH%"
  if errorlevel 1 exit /b 1
  git -C "%DEST%" checkout "%BRANCH%"
  if errorlevel 1 exit /b 1
  git -C "%DEST%" pull --ff-only origin "%BRANCH%"
  if errorlevel 1 exit /b 1
)

cd /d "%DEST%"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -e ".[dev]"
if errorlevel 1 exit /b 1
call npm install
if errorlevel 1 exit /b 1
call npm run build
if errorlevel 1 exit /b 1

set "COREBAT=%TEMP%\omne-core.cmd"
set "SHELLBAT=%TEMP%\omne-shell.cmd"
> "%COREBAT%" echo @echo off
>> "%COREBAT%" echo cd /d "%DEST%"
>> "%COREBAT%" echo call "%DEST%\.venv\Scripts\activate.bat"
>> "%COREBAT%" echo OMNE serve
> "%SHELLBAT%" echo @echo off
>> "%SHELLBAT%" echo cd /d "%DEST%"
>> "%SHELLBAT%" echo "%DEST%\.venv\Scripts\python.exe" -m http.server 4173 --bind 127.0.0.1 --directory shell

start "OMNE core" "%ComSpec%" /k "%COREBAT%"
start "OMNE shell" "%ComSpec%" /k "%SHELLBAT%"
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:4173/"

echo.
echo OMNE simulation is starting.
echo Desktop: http://127.0.0.1:4173/
echo Core:    http://127.0.0.1:8787/health
echo Leave the two new Command Prompt windows open.
echo Later changes:  cd /d "%DEST%" ^& git pull ^& call npm run build
echo Then reload the desktop page. Restart the core window when Python code changed.
exit /b 0

:winget_install
winget install --id %~1 --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
exit /b 0

:refresh_path
set "SYSPATH="
set "USERPATH="
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSPATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USERPATH=%%B"
call set "PATH=%SYSPATH%;%USERPATH%;%ProgramFiles%\Git\cmd;%ProgramFiles%\nodejs;%LocalAppData%\Programs\Git\cmd;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%LocalAppData%\Programs\Python\Launcher"
exit /b 0
