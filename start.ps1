# start.ps1 -- PowerShell wrapper.  Nicer colours than start.bat.
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py = $null
foreach ($candidate in @("python", "python3", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
    Write-Host "python not found in PATH" -ForegroundColor Red
    exit 1
}
& $py "start.py" @args
exit $LASTEXITCODE
