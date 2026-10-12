@echo off
echo ===================================================
echo Footy DataNgin - Full Pipeline Refresh
echo ===================================================
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo [1/4] Running Scraper...
python scraper\run_scrape.py %*
if errorlevel 1 echo [WARNING] Scraper completed with warnings or errors.
echo [2/4] Running Feature Engineering...
python pipeline\features.py
echo [3/4] Running Similarity Modeling...
python pipeline\model_similarity.py
echo [4/4] Validating Pipeline Integrity...
python pipeline\validate.py
echo ===================================================
echo Pipeline Refresh Complete!
echo ===================================================
pause
