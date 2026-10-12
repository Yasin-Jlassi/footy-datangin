@echo off
echo ===================================================
echo Footy DataNgin - Local Ingestion Pipeline Refresh
echo ===================================================
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python scraper\run_scrape.py %*
pause
