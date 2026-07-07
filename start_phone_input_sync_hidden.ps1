$ErrorActionPreference = "SilentlyContinue"
Set-Location -LiteralPath $PSScriptRoot

$listener = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    exit 0
}

$py = Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) {
    Start-Process -FilePath $py.Source -ArgumentList @("-3", "`"$PSScriptRoot\mobile_input_server.py`"") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    exit 0
}

$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($python) {
    Start-Process -FilePath $python.Source -ArgumentList @("`"$PSScriptRoot\mobile_input_server.py`"") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    exit 0
}

exit 1
