$ErrorActionPreference = 'Stop'
$scriptMiniSoc = Join-Path $PSScriptRoot 'app.py'
$pythonMiniSoc = Join-Path $env:USERPROFILE 'AppData\Local\Programs\Python\Python312\python.exe'

if (Test-Path -LiteralPath $pythonMiniSoc) {
    & $pythonMiniSoc $scriptMiniSoc @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $scriptMiniSoc @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $scriptMiniSoc @args
} else {
    throw 'Instala Python 3.11 o posterior para iniciar el Mini SOC.'
}

exit $LASTEXITCODE
