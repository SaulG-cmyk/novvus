# Dev environment for Novvus module development.
# Los secretos se leen de entrega/_build/docker/.env, que no se versiona.
# Copia .env.example a .env y sustituye los valores antes de usar este script.
$repo = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo 'entrega\_build\docker\.env'
if (-not (Test-Path $envFile)) {
  throw "No se encontró $envFile. Cópialo de .env.example y rellénalo antes de continuar."
}

$vals = @{}
foreach ($line in Get-Content $envFile) {
  if ($line -match '^\s*([A-Z0-9_]+)=(.*)$') { $vals[$matches[1]] = $matches[2].Trim('"') }
}

$env:NOVVUS_DATABASE_URL = "postgres://$($vals['POSTGRES_USER']):$($vals['POSTGRES_PASSWORD'])@localhost:5432/$($vals['POSTGRES_DB'])"
$env:NOVVUS_KERNEL_URL = 'http://localhost:8000'
$env:NOVVUS_INTERNAL_HMAC_SECRET = $vals['NOVVUS_INTERNAL_HMAC_SECRET']
$env:NOVVUS_MODULE_DB_PASSWORD = $vals['NOVVUS_MODULE_DB_PASSWORD']
Write-Host 'Dev env loaded from local .env (secretos no mostrados).'
