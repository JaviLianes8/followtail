# Build and upload to PyPI. Run scripts/check.ps1 first.
# The name must not already exist on PyPI; the token is read from a secret store, never git.
$ErrorActionPreference = "Stop"

# Works on both Windows PowerShell 5.1 and pwsh 7 (generic catch, no PS7-only types).
$taken = $true
try {
    Invoke-WebRequest -UseBasicParsing "https://pypi.org/pypi/followtail/json" | Out-Null
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 404) { $taken = $false } else { throw }
}
if ($taken) { throw "The name 'followtail' already exists on PyPI. Choose another before publishing." }

$token = $env:PYPI_TOKEN
if (-not $token -and (Test-Path "C:\secrets\pypi-token.txt")) {
    $token = (Get-Content "C:\secrets\pypi-token.txt" -Raw).Trim()
}
if (-not $token) {
    throw "No PyPI token. Set `$env:PYPI_TOKEN or save it to C:\secrets\pypi-token.txt (never commit it)."
}

Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
python -m build
python -m twine check dist/*

$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = $token
try { python -m twine upload dist/* } finally { Remove-Item Env:\TWINE_PASSWORD -ErrorAction SilentlyContinue }
