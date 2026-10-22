@echo off
rem ============================================================================
rem  Збирання програми для Windows. Запускати на Windows 10/11 x64 з Python 3.12+
rem  (https://www.python.org/downloads/ --- при встановленні позначте "Add python.exe to PATH").
rem  Результат: dist\PaintByNumbers\PaintByNumbers.exe  та  dist\PaintByNumbers.zip
rem ============================================================================
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 ( set PY=py -3 ) else ( set PY=python )

if not exist .venv-build (
    echo [1/5] Створення віртуального середовища...
    %PY% -m venv .venv-build || goto :fail
)
call .venv-build\Scripts\activate.bat || goto :fail

echo [2/5] Встановлення залежностей (потрібен інтернет)...
python -m pip install --upgrade pip || goto :fail
python -m pip install -r packaging\requirements-build.txt || goto :fail

echo [3/5] Тести...
python -m pip install pytest || goto :fail
python -m pytest -q || goto :fail

echo [4/5] Збирання PyInstaller (кілька хвилин)...
pyinstaller packaging\pbn.spec --noconfirm --clean --distpath dist --workpath build || goto :fail

echo [5/5] Самоперевірка зібраної програми...
dist\PaintByNumbers\pbn-cli.exe --selftest || goto :fail

powershell -NoProfile -Command "Compress-Archive -Path 'dist\PaintByNumbers' -DestinationPath 'dist\PaintByNumbers.zip' -Force"
echo.
echo ГОТОВО: dist\PaintByNumbers\PaintByNumbers.exe
echo Архів для передачі: dist\PaintByNumbers.zip
pause
exit /b 0

:fail
echo.
echo ПОМИЛКА: збирання перервано. Перегляньте повідомлення вище.
pause
exit /b 1
