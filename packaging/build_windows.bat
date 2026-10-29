@echo off
rem ============================================================================
rem  Збирання ArtPhoenix Studio для Windows 10/11 x64 через uv (https://docs.astral.sh/uv/).
rem  uv сам завантажить Python 3.12 і залежності. Встановлення uv (PowerShell):
rem      powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
rem  Результат: dist\ArtPhoenixStudio\ArtPhoenixStudio.exe  та  dist\ArtPhoenixStudio.zip
rem ============================================================================
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
set UV_PROJECT_ENVIRONMENT=.venv-build

where uv >nul 2>nul
if errorlevel 1 (
    echo Не знайдено uv. Встановіть: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    goto :fail
)

echo [1/4] Залежності (uv sync, Python 3.12, група build)...
uv sync --python 3.12 --no-dev --group build || goto :fail

echo [2/4] Тести...
set QT_QPA_PLATFORM=offscreen
uv run --no-sync --with pytest python -m pytest -q || goto :fail

echo [3/4] Збирання PyInstaller (кілька хвилин)...
uv run --no-sync pyinstaller packaging\pbn.spec --noconfirm --clean --distpath dist --workpath build || goto :fail

echo [4/4] Самоперевірка зібраної програми...
dist\ArtPhoenixStudio\ArtPhoenixStudio-cli.exe --selftest || goto :fail

powershell -NoProfile -Command "Compress-Archive -Path 'dist\ArtPhoenixStudio' -DestinationPath 'dist\ArtPhoenixStudio.zip' -Force"
echo.
echo ГОТОВО: dist\ArtPhoenixStudio\ArtPhoenixStudio.exe
echo Архів для передачі: dist\ArtPhoenixStudio.zip
pause
exit /b 0

:fail
echo.
echo ПОМИЛКА: збирання перервано. Перегляньте повідомлення вище.
pause
exit /b 1
