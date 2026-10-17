@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --onefile --windowed --name IQ_Studio main.py
echo.
echo الملف الجاهز: dist\IQ_Studio.exe
pause
