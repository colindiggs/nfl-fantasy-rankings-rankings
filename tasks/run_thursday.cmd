@echo off
cd /d "%~dp0..\scripts"
if not exist ..\logs mkdir ..\logs
python runner.py thursday >> ..\logs\task.log 2>&1
