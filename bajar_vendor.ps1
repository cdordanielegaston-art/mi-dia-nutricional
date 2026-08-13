# ─────────────────────────────────────────────────────────────────────────────
# Baja a vendor\ las librerias que el index.html toma del CDN, para que el bridge
# las sirva por Tailscale en vez de que el celular las baje de internet.
#
# Por que: medido el 2026-08-13, los 4 CDN son 3,3 MB (Babel solo son 2,78 MB), y
# como por HTTP contra una IP no hay contexto seguro, el service worker NO se
# registra: sin cache, el celular se los bajaba enteros EN CADA CARGA.
# Servidos desde el bridge y comprimidos quedan en ~757 KB, y la segunda carga
# no transfiere nada (Cache-Control immutable).
#
# vendor\ NO va al repo (esta en .gitignore). Correr esto en cada PC que aloje
# el bridge. Si falta un archivo, el bridge deja esa libreria apuntando al CDN
# y lo avisa en el log.
#
#   powershell -ExecutionPolicy Bypass -File bajar_vendor.ps1
# ─────────────────────────────────────────────────────────────────────────────
$destino = Join-Path $PSScriptRoot "vendor"
New-Item -ItemType Directory -Force -Path $destino | Out-Null

# Tienen que coincidir con VENDOR_LOCAL de mdn_bridge.py y con el index.html
$libs = [ordered]@{
  "react.min.js"     = "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"
  "react-dom.min.js" = "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"
  "babel.min.js"     = "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"
  "jspdf.umd.min.js" = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"
}

$fallaron = 0
foreach ($nombre in $libs.Keys) {
  $archivo = Join-Path $destino $nombre
  # curl.exe con --ssl-no-revoke: Norton rompe el chequeo de revocacion en esta PC
  curl.exe --ssl-no-revoke -sfL -o $archivo $libs[$nombre]
  if ((Test-Path $archivo) -and (Get-Item $archivo).Length -gt 1024) {
    "{0,-20} {1,8:N1} KB" -f $nombre, ((Get-Item $archivo).Length / 1KB) | Write-Host -ForegroundColor Green
  } else {
    "{0,-20} FALLO" -f $nombre | Write-Host -ForegroundColor Red
    $fallaron++
  }
}

Write-Host ""
if ($fallaron) {
  Write-Host "$fallaron sin bajar: esas salen del CDN (mas lento desde el celular)." -ForegroundColor Yellow
} else {
  $kb = (Get-ChildItem $destino -File | Measure-Object Length -Sum).Sum / 1KB
  Write-Host ("Listo: {0:N0} KB en vendor\. Reinicia el bridge para que las sirva." -f $kb) -ForegroundColor Green
}
