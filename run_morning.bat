@echo off
cd /d "%~dp0"
venv\Scripts\python.exe scripts\run_morning.py >> data\run.log 2>&1
