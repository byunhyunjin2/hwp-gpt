@echo off
rem 개발판 실행: 더블클릭하면 콘솔 없이 패널이 뜬다. 한글 안에서 시작하려면 --embed
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0run.pyw" %*
