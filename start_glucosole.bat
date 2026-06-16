@echo off
REM GlycoSole Recorder starten (Doppelklick)
cd /d "%~dp0"
python glycosole_recorder.py
REM Fenster offen lassen, falls ein Fehler kam
if errorlevel 1 (
    echo.
    echo Es gab ein Problem. Bitte Screenshot machen und Ruben zeigen.
    pause
)
