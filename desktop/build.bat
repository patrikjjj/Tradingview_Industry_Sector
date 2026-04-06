@echo off
setlocal

cd /d "%~dp0\.."

echo Installing build dependency...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo Failed to install PyInstaller.
  exit /b 1
)

echo Building TradingSectorPanel and TradingSectorNativeHost...
python -m PyInstaller --noconfirm --clean TradingSectorPanel.spec
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo.
echo Build complete.
echo EXE folder: dist\TradingSectorPanel
echo Panel app: dist\TradingSectorPanel\TradingSectorPanel.exe
echo Native host: dist\TradingSectorPanel\TradingSectorNativeHost.exe
echo.
pause
