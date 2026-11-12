<#
 Buzz uninstaller (Windows, normal user account). Removes the background tasks, stops Buzz and removes its Python environment.
 Your reels, accounts and settings are kept unless you choose otherwise. -DryRun only shows what would happen.
#>
param([switch]$DryRun)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Act($text, [scriptblock]$act) { if ($DryRun) { Write-Host "[dry run] $text" } else { Write-Host $text; try { & $act } catch { Write-Host "  (skipped: $($_.Exception.Message))" -ForegroundColor Yellow } } }

Write-Host "Buzz uninstaller for: $root" -ForegroundColor Cyan
if (-not $DryRun) {
    $go = Read-Host "Remove Buzz's background tasks and Python environment? Your reels and settings stay. [Y/n]"
    if ($go -and $go.Trim().ToLower() -eq "n") { Write-Host "Nothing changed."; exit 0 }
}
$keys = $false; $wipe = $false
if (-not $DryRun) {
    $k = Read-Host "Also remove your saved keys (Claude, Google voice, Pexels, mail) from Windows Credential Manager? [y/N]"
    $keys = ($k -and $k.Trim().ToLower() -eq "y")
    $w = Read-Host "Also delete the whole Buzz folder, INCLUDING all your reels and accounts? Type DELETE to confirm, or press Enter to keep them"
    $wipe = ($w -eq "DELETE")
}

Act "Stopping the Buzz background tasks" {
    foreach ($t in @("Buzz Worker", "Buzz Page")) { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue }
    $lock = Join-Path $root "Work\worker.lock"
    if (Test-Path $lock) { Stop-Process -Id ([int](Get-Content $lock)) -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object { $_.ExecutablePath -like "$root\.venv\*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
Act "Removing the Buzz tasks from Task Scheduler" {
    foreach ($t in @("Buzz Worker", "Buzz Page")) { Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue }
}
if ($keys -or $DryRun) {
    Act "Removing saved keys from Windows Credential Manager" {
        $py = Join-Path $root ".venv\Scripts\python.exe"
        if (Test-Path $py) {
            $tmp = Join-Path $env:TEMP "buzz_rm_keys.py"
            Set-Content -Path $tmp -Encoding ascii -Value @("import keyring", "for n in ('anthropic','google_tts','pexels','smtp'):", "    try: keyring.delete_password('ai-reel-studio', n)", "    except Exception: pass")
            & $py $tmp
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        }
    }
}
if ($wipe) {
    Write-Host "Deleting the Buzz folder (including reels and accounts) in a moment..."
    Start-Process cmd -ArgumentList "/c timeout /t 4 >nul & rmdir /s /q `"$root`"" -WindowStyle Hidden
    exit 0
}
Act "Removing the Python environment (.venv)" { Remove-Item (Join-Path $root ".venv") -Recurse -Force -ErrorAction Stop }
Act "Removing the install marker" { Remove-Item (Join-Path $root ".installed") -Force -ErrorAction SilentlyContinue }
if ($DryRun) { Write-Host ""; Write-Host "Dry run finished. Nothing was changed." -ForegroundColor Green; exit 0 }
Write-Host ""
Write-Host "Done. Buzz is uninstalled. Your reels, accounts and settings are still in $root." -ForegroundColor Green
Write-Host "You can delete that folder yourself whenever you like. (Python and FFmpeg were left installed.)"
