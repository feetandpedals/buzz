@echo off
schtasks /Change /TN "Buzz Worker" /DISABLE >nul
for /f %%p in ('type "%~dp0Work\worker.lock"') do taskkill /PID %%p /F >nul
del "%~dp0Work\worker.lock" >nul 2>&1
echo Worker stopped and switched off. Use 'Start Buzz' to turn it on again.
timeout /t 5 >nul
