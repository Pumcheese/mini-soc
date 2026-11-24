$ErrorActionPreference = 'Stop'
$scriptMiniSoc = Join-Path $PSScriptRoot 'app.py'
$candidatosMiniSoc = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidatosMiniSoc += ,@('py', '-3')
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    $candidatosMiniSoc += ,@('python')
}
if ($env:LOCALAPPDATA) {
    $instalacionesMiniSoc = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $instalacionesMiniSoc) {
        Get-ChildItem -LiteralPath $instalacionesMiniSoc -Directory -Filter 'Python*' |
            Sort-Object Name -Descending | ForEach-Object {
                $ejecutableMiniSoc = Join-Path $_.FullName 'python.exe'
                if (Test-Path -LiteralPath $ejecutableMiniSoc) {
                    $candidatosMiniSoc += ,@($ejecutableMiniSoc)
                }
            }
    }
}
foreach ($candidatoMiniSoc in $candidatosMiniSoc) {
    $comandoMiniSoc = $candidatoMiniSoc[0]
    $prefijoMiniSoc = @($candidatoMiniSoc | Select-Object -Skip 1)
    & $comandoMiniSoc @prefijoMiniSoc -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) {
        & $comandoMiniSoc @prefijoMiniSoc $scriptMiniSoc @args
        exit $LASTEXITCODE
    }
}
throw 'No se encontró Python 3.11 o posterior. Instálalo o ejecuta app.py con la ruta de tu intérprete.'
