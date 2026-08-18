@echo off
cd /d "%~dp0..\scripts"
if not exist ..\logs mkdir ..\logs
python runner.py sync >> ..\logs\task.log 2>&1
