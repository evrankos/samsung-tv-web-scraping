# ==============================================================================
# Windows Task Scheduler Setup: Samsung Weekly Scraper (Every 7 Days)
# ==============================================================================
# This script schedules the Samsung scraping and database update pipeline
# to run automatically every 7 days (e.g. every Sunday at 02:00 AM local time).
# Run this script in PowerShell as Administrator or standard user.
# ==============================================================================

$TaskName = "Samsung_Weekly_Scraper_Pipeline"
$ProjectDir = "d:\Projects\samsung-tv-web-scraping"
$BatchPath = "$ProjectDir\run_pipeline.bat"
$Arguments = "--scrape-all --alerts"

Write-Host "Configuring Windows Scheduled Task: $TaskName" -ForegroundColor Cyan
Write-Host "Target Directory: $ProjectDir" -ForegroundColor Gray
Write-Host "Executable:       $BatchPath $Arguments" -ForegroundColor Gray

# Create scheduled task action
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchPath`" $Arguments > `"$ProjectDir\logs_scheduler.txt`" 2>&1" `
    -WorkingDirectory $ProjectDir

# Create 7-day trigger (Weekly on Sunday at 2:00 AM)
$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Sunday `
    -At "02:00AM"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

try {
    # Unregister existing task if present
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    
    # Register the new task
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Automated 7-day Samsung Catalog Scraper and SQLite Price Tracker Updater"

    Write-Host "`nTask '$TaskName' registered successfully!" -ForegroundColor Green
    Write-Host "Schedule: Every Sunday at 02:00 AM (Repeats every 7 days)" -ForegroundColor Green
    Write-Host "You can test-run this task anytime with: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
} catch {
    Write-Host "`nFailed to register scheduled task: $_" -ForegroundColor Red
    Write-Host "Please ensure you run PowerShell with adequate permissions." -ForegroundColor Yellow
}
