@echo off
setlocal EnableExtensions
cd /d "%~dp0"

py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto :error

if exist "dist\RCCarsLauncher.exe" del /q "dist\RCCarsLauncher.exe" >nul 2>&1
if exist "dist\RCCarsLauncher" rmdir /s /q "dist\RCCarsLauncher"
if exist "dist\RCCarsLauncher_Portable.zip" del /q "dist\RCCarsLauncher_Portable.zip" >nul 2>&1

if exist "launcher_icon.ico" goto :build_with_icon

py -3 -m PyInstaller --noconfirm --windowed --name RCCarsLauncher --onedir --contents-directory "_runtime" ^
  launcher.py
if errorlevel 1 goto :error
goto :post_build

:build_with_icon
py -3 -m PyInstaller --noconfirm --windowed --name RCCarsLauncher --onedir --contents-directory "_runtime" ^
  --icon "launcher_icon.ico" ^
  launcher.py
if errorlevel 1 goto :error

:post_build
set "OUTDIR=dist\RCCarsLauncher"
if not exist "%OUTDIR%" goto :error
if not exist "%OUTDIR%\Tools" mkdir "%OUTDIR%\Tools"
copy /y "launcher_config.json" "%OUTDIR%\launcher_config.json" >nul
copy /y "social_links.json" "%OUTDIR%\social_links.json" >nul
if exist "launcher_icon.ico" copy /y "launcher_icon.ico" "%OUTDIR%\launcher_icon.ico" >nul
if exist "Tools" xcopy "Tools\*" "%OUTDIR%\Tools" /E /I /H /K /Y >nul

if exist "dist\RCCarsLauncher_Portable.zip" del /q "dist\RCCarsLauncher_Portable.zip" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%OUTDIR%\*' -DestinationPath 'dist\RCCarsLauncher_Portable.zip' -Force"
if errorlevel 1 goto :error

echo.
echo Build complete:
echo   EXE: %CD%\%OUTDIR%\RCCarsLauncher.exe
echo   Package for GitHub Releases: %CD%\dist\RCCarsLauncher_Portable.zip
echo.
echo Distribute the whole RCCarsLauncher folder, not only the EXE.
echo For GitHub updates, attach RCCarsLauncher_Portable.zip to each release.
echo The _runtime directory contains PyInstaller's packaged Python/Qt runtime.
echo The data directory is created at runtime and stores settings and backups.
pause
exit /b 0

:error
echo Build failed. See the error above.
pause
exit /b 1
