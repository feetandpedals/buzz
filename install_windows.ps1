<#
 Buzz installer (Windows 10/11, normal user account, no administrator needed).
 Safe to run again: it only adds what is missing.
 Switches: -SkipSystemInstalls (do not touch Python/FFmpeg), -SkipTasks (do not register background tasks),
           -SkipKeys (do not ask for the Claude key), -NoStart (do not start the app at the end)
#>
param([switch]$SkipSystemInstalls, [switch]$SkipTasks, [switch]$SkipKeys, [switch]$NoStart)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
function Step($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }

Step "1/8  Python 3.12"
$py = $null
foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe")) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) { $cmd = Get-Command python -ErrorAction SilentlyContinue; if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $py = $cmd.Source } }
if (-not $py -and -not $SkipSystemInstalls) {
    winget install --id Python.Python.3.12 --scope user -e --silent --accept-package-agreements --accept-source-agreements
    $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
}
if (-not $py -or -not (Test-Path $py)) { throw "Python 3.12 was not found. Install it from python.org (tick 'Add to PATH') and run this again." }
Write-Host "Using $py"

Step "2/8  FFmpeg"
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ff) { $ff = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1 }
if (-not $ff -and -not $SkipSystemInstalls) { winget install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements }
Write-Host "FFmpeg ready (src\common.py finds it by itself)."

Step "3/8  Python environment (this takes several minutes)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Step "4/8  Face detector (OpenCV 4 in its own folder)"
if (-not (Test-Path "assets\cv4\cv2")) { & .\.venv\Scripts\python.exe -m pip install --target assets\cv4 --no-deps -r requirements-cv4.txt }

Step "5/8  Folders"
foreach ($d in @("Reels In", "Reels Out", "Work")) { New-Item -ItemType Directory -Force $d | Out-Null }

Step "6/8  Claude key (stored in Windows Credential Manager, never in a file)"
if (-not $SkipKeys) {
    $have = & .\.venv\Scripts\python.exe -c "import keyring;print(bool(keyring.get_password('ai-reel-studio','anthropic')))"
    if ($have -ne "True") {
        $sec = Read-Host "Paste your Claude API key (press Enter to skip; you can add it later under Settings)" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
        if ($plain) {
            $env:RS_KEY = $plain
            & .\.venv\Scripts\python.exe -c "import os,keyring;keyring.set_password('ai-reel-studio','anthropic',os.environ['RS_KEY'])"
            Remove-Item Env:RS_KEY
            Write-Host "Saved."
        } else { Write-Host "Skipped. Add the key later on the Settings tab." }
    } else { Write-Host "A Claude key is already saved." }
}

Step "7/8  Background tasks (start at sign-in, watchdog every 5 minutes)"
if (-not $SkipTasks) {
    function Register-Reel($name, $exe, $args) {
        $action = New-ScheduledTaskAction -Execute $exe -Argument $args -WorkingDirectory $root
        $t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
        $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
        $pr = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $name -Action $action -Trigger @($t1, $t2) -Settings $set -Principal $pr -Force | Out-Null
        Write-Host "Registered: $name"
    }
    $pw = "$root\.venv\Scripts\pythonw.exe"
    Register-Reel "Buzz Worker" $pw "`"$root\src\worker.py`""
    Register-Reel "Buzz Page" $pw "-m streamlit run `"$root\src\app.py`" --server.port 8501 --server.headless true --browser.gatherUsageStats false --server.address 127.0.0.1 --server.maxUploadSize 4000"
} else { Write-Host "Skipped." }

Step "8/8  Start"
if (-not $NoStart -and -not $SkipTasks) {
    Start-ScheduledTask -TaskName "Buzz Worker"
    Start-ScheduledTask -TaskName "Buzz Page"
    Start-Sleep 8
    Start-Process "http://127.0.0.1:8501"
}
Write-Host ""
Write-Host "Done. Open http://127.0.0.1:8501 - the first screen creates the owner account." -ForegroundColor Green
