$ErrorActionPreference = 'Stop'
try {
    $launcherPath = Join-Path $PSScriptRoot 'launcher.py'
    $pythonPath = $null
    foreach ($candidate in @('py', 'python', 'python3')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $probeArgs = @('-c', 'import sys; print(sys.executable) if sys.version_info >= (3,10) else sys.exit(1)')
            if ($candidate -eq 'py') { $probeArgs = @('-3') + $probeArgs }
            $probe = @(& $candidate @probeArgs 2>$null)
            if ($LASTEXITCODE -eq 0 -and $probe -and (Test-Path -LiteralPath $probe[-1])) {
                $pythonPath = [string]$probe[-1]
                break
            }

        }
    }
    if (-not $pythonPath) { throw 'Python 3.10+ is required. Install Python from python.org, then open START_GAME again.' }
    $windowlessPython = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $windowlessPython)) { $windowlessPython = $pythonPath }
    Start-Process -FilePath $windowlessPython -ArgumentList @('"' + $launcherPath + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'RIFT', 'OK', 'Error') | Out-Null
}
