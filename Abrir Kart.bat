@echo off
title Kart - Meus Resultados
cd /d "%~dp0"
python server.py
if errorlevel 1 pause
