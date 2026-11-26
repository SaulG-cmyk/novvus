# Dev environment for Novvus module development
$env:NOVVUS_DATABASE_URL = "postgres://novvus:c60d9af8f4bcc458b9bbf45d0ef206f4@localhost:5432/novvus"
$env:NOVVUS_KERNEL_URL = "http://localhost:8000"
$env:NOVVUS_INTERNAL_HMAC_SECRET = "967699a93e53602c74a49e40fa89f2dc3d41dc1dc37e9e95210576b3f8dcf8b7"
$env:NOVVUS_MODULE_DB_PASSWORD = "a801f7fe59c7a6bdfd68b29e778a08f7"
Write-Host "Dev env loaded. NOVVUS_DATABASE_URL=$env:NOVVUS_DATABASE_URL"
Write-Host "Kernel: $env:NOVVUS_KERNEL_URL"
