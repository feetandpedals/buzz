<#
 Buzz installer (Windows 10/11, normal user account, no administrator needed).
 Safe to run again: it only adds what is missing.
 Switches: -SkipSystemInstalls (do not touch Python/FFmpeg), -SkipTasks (do not register background tasks),
           -NoStart (do not start the app at the end),
           -InstallDir <folder> (install there without asking), -Here (install in this folder, no copy)
#>
param([switch]$SkipSystemInstalls, [switch]$SkipTasks, [switch]$NoStart, [string]$InstallDir = "", [switch]$Here)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
trap {
    Write-Host ""
    Write-Host "Something went wrong: $_" -ForegroundColor Red
    Write-Host "Please send a photo of this window. A copy is saved in Work\install.log" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch {}
    Read-Host "Press Enter to close"
    exit 1
}

# Where to install: ask once (default Documents\Buzz), copy the files there, and continue from that folder.
if (-not $Here -and -not (Test-Path (Join-Path $root ".installed"))) {
    if (-not $InstallDir) {
        $default = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Buzz"
        $ans = Read-Host "Install Buzz into '$default'? Press Enter to accept, or type another folder"
        $InstallDir = if ($ans.Trim()) { $ans.Trim().Trim('"') } else { $default }
    }
    $target = [IO.Path]::GetFullPath($InstallDir)
    if ($target.TrimEnd('\') -ne $root.TrimEnd('\')) {
        New-Item -ItemType Directory -Force $target | Out-Null
        Write-Host "Copying Buzz to $target ..."
        Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -notin @(".venv", "Work", "Reels In", "Reels Out") } | Copy-Item -Destination $target -Recurse -Force
        $fwd = @(); foreach ($k in @("SkipSystemInstalls", "SkipTasks", "NoStart")) { if ((Get-Variable $k).Value) { $fwd += "-$k" } }
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target "install_windows.ps1") -Here @fwd
        exit $LASTEXITCODE
    }
}
New-Item -ItemType File -Force (Join-Path $root ".installed") | Out-Null
Set-Location $root
New-Item -ItemType Directory -Force "Work" | Out-Null
try { Start-Transcript -Path (Join-Path $root "Work\install.log") -Append | Out-Null } catch {}
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

Step "6/8  Claude key"
Write-Host "Nothing to do here: you add your Claude key inside Buzz, on the Settings tab."

Step "7/8  Background tasks (start at sign-in, watchdog every 5 minutes)"
if (-not $SkipTasks) {
    function Register-Reel($name, $exe, $taskArgs) {
        $action = New-ScheduledTaskAction -Execute $exe -Argument $taskArgs -WorkingDirectory $root
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
try { Stop-Transcript | Out-Null } catch {}
