$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\venvs\p313\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "pdf_to_jats\main.py"

if (-not (Test-Path -LiteralPath $python)) {
    $fallback = Join-Path $projectRoot "p313\Scripts\python.exe"
    if (Test-Path -LiteralPath $fallback) {
        $python = $fallback
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) {
            $python = $command.Source
        } else {
            $launcher = Get-Command py -ErrorAction SilentlyContinue
            if ($launcher) {
                $python = (& $launcher.Source -3 -c "import sys; print(sys.executable)").Trim()
            } else {
                throw "Python was not found. Install Python 3 and add it to PATH, or create C:\venvs\p313."
            }
        }
    }
}

if (-not (Test-Path -LiteralPath $entrypoint)) {
    throw "Application entrypoint not found: $entrypoint"
}

& $python $entrypoint
