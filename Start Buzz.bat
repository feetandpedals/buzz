@echo off
schtasks /Change /TN "Buzz Worker" /ENABLE >nul
schtasks /Change /TN "Buzz Page" /ENABLE >nul
schtasks /Run /TN "Buzz Worker" >nul
schtasks /Run /TN "Buzz Page" >nul
echo Started. Open the page with the file 'Open Buzz'.
timeout /t 5 >nul
