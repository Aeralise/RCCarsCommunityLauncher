@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto :error

if exist "launcher_icon.ico" goto :build_with_icon

py -3 -m PyInstaller --noconfirm --clean --windowed --name RCCarsLauncher --onefile ^
  --add-data "rccars_pack_tool.py;." ^
  --add-data "launcher_config.json;." ^
  --add-data "social_links.json;." ^
  launcher.py
if errorlevel 1 goto :error
goto :post_build

:build_with_icon
py -3 -m PyInstaller --noconfirm --clean --windowed --name RCCarsLauncher --onefile ^
  --icon "launcher_icon.ico" ^
  --add-data "launcher_icon.ico;." ^
  --add-data "rccars_pack_tool.py;." ^
  --add-data "launcher_config.json;." ^
  --add-data "social_links.json;." ^
  launcher.py
if errorlevel 1 goto :error

:post_build
if not exist "dist\Tools" mkdir "dist\Tools"
copy /y "launcher_config.json" "dist\launcher_config.json" >nul
copy /y "social_links.json" "dist\social_links.json" >nul
echo.
echo Build complete: %CD%\dist\RCCarsLauncher.exe
echo Distribute RCCarsLauncher.exe together with launcher_config.json, social_links.json and the Tools folder.
if not exist "launcher_icon.ico" echo NOTE: launcher_icon.ico was not found; the custom EXE icon was not embedded.
pause
exit /b 0
:error
echo Build failed. See the error above.
pause
exit /b 1
