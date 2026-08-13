# ─────────────────────────────────────────────────────────────────────────────
# Deja el MDN Bridge arrancando solo al iniciar sesion en Windows.
#
# Sin esto, despues de reiniciar la PC la app abre pero el chat no anda hasta
# arrancar el bridge a mano — y desde el celular no hay forma de arrancarlo.
#
# Corre SIN consola (CreateNoWindow via -WindowStyle Hidden) y con instancia
# unica: si ya hay un bridge escuchando, el proceso nuevo se va solo.
#
# Para instalarlo:     powershell -ExecutionPolicy Bypass -File instalar_autostart.ps1
# Para sacarlo:        powershell -ExecutionPolicy Bypass -File instalar_autostart.ps1 -Quitar
# ─────────────────────────────────────────────────────────────────────────────
param([switch]$Quitar)

$TAREA  = "MDN Bridge"
$SCRIPT = Join-Path $PSScriptRoot "mdn_bridge.py"

if ($Quitar) {
    if (Get-ScheduledTask -TaskName $TAREA -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TAREA -Confirm:$false
        Write-Host "Listo: '$TAREA' desinstalada. El bridge ya no arranca solo." -ForegroundColor Yellow
    } else {
        Write-Host "No estaba instalada." -ForegroundColor DarkGray
    }
    return
}

if (-not (Test-Path $SCRIPT)) {
    Write-Host "No encuentro mdn_bridge.py en $PSScriptRoot" -ForegroundColor Red
    exit 1
}

# pythonw.exe: sin consola y, por lo tanto, sin conhost. Antes moria mudo porque
# logging.basicConfig arma un StreamHandler(sys.stderr) y bajo pythonw stderr es None;
# el bridge ahora redirige stdout/stderr al log ANTES de tocar logging, asi que anda.
# Si igual fallara, el motivo queda escrito en logs\bridge_<fecha>.log.
$python = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { Write-Host "No encuentro python en el PATH" -ForegroundColor Red; exit 1 }

$accion    = New-ScheduledTaskAction -Execute $python -Argument "`"$SCRIPT`"" -WorkingDirectory $PSScriptRoot
$disparo   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$opciones  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TAREA -Action $accion -Trigger $disparo `
    -Settings $opciones -Principal $principal -Force `
    -Description "Backend de Mi Dia Nutricional: conecta la app con la suscripcion Claude Max (puerto 8793)." | Out-Null

Write-Host ""
Write-Host "Listo: el bridge arranca solo al iniciar sesion." -ForegroundColor Green
Write-Host "  Tarea    : $TAREA"
Write-Host "  Reintenta: 3 veces, cada 1 min, si falla"
Write-Host "  Ventana  : ninguna (oculta)"
Write-Host ""
Write-Host "Para probarla sin reiniciar:  Start-ScheduledTask -TaskName '$TAREA'" -ForegroundColor DarkGray
Write-Host "Para sacarla:                 .\instalar_autostart.ps1 -Quitar" -ForegroundColor DarkGray
