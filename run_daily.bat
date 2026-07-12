@echo off
cd /d "%~dp0"
venv\Scripts\python.exe main.py >> data\run.log 2>&1
