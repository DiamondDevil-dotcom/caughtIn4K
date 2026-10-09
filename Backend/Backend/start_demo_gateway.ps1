param(
    [string]$ListenAddress = "192.168.50.198"
)

$ErrorActionPreference = "Stop"
$address = [System.Net.IPAddress]::Parse($ListenAddress)
$bytes = $address.GetAddressBytes()
if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
    -not ($bytes[0] -eq 10 -or
          ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
          ($bytes[0] -eq 192 -and $bytes[1] -eq 168))) {
    throw "The demo gateway must bind to a private IPv4 address on this laptop."
}
$null = Get-NetIPAddress -IPAddress $ListenAddress -AddressFamily IPv4 -ErrorAction Stop
$python = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) {
    throw "The project Python environment is missing."
}

if (-not $env:GHOST_ROUTER_TOKEN -or $env:GHOST_ROUTER_TOKEN.Length -lt 32) {
    $token = Read-Host "Enter the existing Pi GHOST_ROUTER_TOKEN" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($token)
    try {
        $env:GHOST_ROUTER_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        Remove-Variable token, pointer
    }
}
if ($env:GHOST_ROUTER_TOKEN.Length -lt 32) {
    throw "Use the existing Pi token with at least 32 characters."
}
$env:GHOST_BACKEND_ROLE = "gateway"
$env:ROUTER_API_URL = "http://192.168.50.1:8001"
$env:GHOST_CLOUD_ACCOUNTS_ENABLED = "false"
Write-Host "Demo sender gateway: http://${ListenAddress}:8002"
Write-Host "Keep this terminal open. Sign in with your existing Pi-household account."
Write-Host "This isolated Wi-Fi demo uses HTTP. Do not expose it on a public tunnel."
& $python -m uvicorn app:app --app-dir $PSScriptRoot --host $ListenAddress --port 8002
if ($LASTEXITCODE -ne 0) {
    throw "Demo gateway exited with code $LASTEXITCODE."
}
