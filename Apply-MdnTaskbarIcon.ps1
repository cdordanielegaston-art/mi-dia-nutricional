param(
  [string]$Url = '',
  [switch]$LaunchLocal,
  [ValidateRange(2, 30)]
  [int]$WaitSeconds = 12
)

$ErrorActionPreference = 'Stop'

$appRoot = $PSScriptRoot
$iconPath = Join-Path $appRoot 'hot-pot.ico'
$localFile = Join-Path $appRoot 'index.html'
$nativeDll = 'D:\Datos Gaston\Desktop\Explorer con iconos\Native\EcdIconBar.Native.dll'
$silentLauncher = 'D:\Datos Gaston\Desktop\Explorer con iconos\Native\EcdSilentLauncher.exe'
$edgeCandidates = @(
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
)
$edge = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$windowTitle = 'Mi D' + [char]0x00ED + 'a Nutricional'
$appId = 'Gasaton.WebIconBar.MiDiaNutricional'
$logPath = Join-Path $appRoot 'logs\taskbar-icon.log'
$refreshScript = Join-Path $appRoot 'refresh_mdn_taskbar.py'
$pythonwCandidates = @(
  'C:\Python314\pythonw.exe',
  'C:\Python313\pythonw.exe',
  'C:\Python312\pythonw.exe'
)
$pythonw = $pythonwCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1

if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) { exit 2 }
if (-not (Test-Path -LiteralPath $nativeDll -PathType Leaf)) { exit 3 }
if (-not (Test-Path -LiteralPath $silentLauncher -PathType Leaf)) { exit 4 }

if (-not ('WebAppIconNative' -as [type])) {
  Add-Type -Path $nativeDll
}

$localUrl = 'file:///' + (($localFile -replace '\\', '/') -replace ' ', '%20')
$relaunchCommand = "`"$silentLauncher`" ps1 `"$PSCommandPath`" -LaunchLocal -WaitSeconds 12"
$iconResource = "$iconPath,0"

if ($LaunchLocal) {
  $Url = $localUrl
}

if (-not [string]::IsNullOrWhiteSpace($Url)) {
  if ([string]::IsNullOrWhiteSpace($edge)) { exit 5 }
  $safeUrl = $Url.Replace('"', '%22')
  Start-Process -FilePath $edge -ArgumentList "--app=`"$safeUrl`"" | Out-Null
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$appliedHandles = @{}

do {
  foreach ($window in @([WebAppIconNative]::GetVisibleWindows())) {
    if ($window.Title -cne $windowTitle) { continue }

    try {
      $process = Get-Process -Id ([int]$window.ProcessId) -ErrorAction Stop
      if ($process.ProcessName -ne 'msedge') { continue }

      $hwnd = [IntPtr]$window.Hwnd
      [void][WebAppIconNative]::SetIcons($hwnd, $iconPath, 0)
      [void][WebAppIconNative]::SetWindowAppUserModel(
        $hwnd,
        $appId,
        $relaunchCommand,
        'Mi Dia Nutricional',
        $iconResource
      )
      $appliedHandles[$hwnd.ToInt64()] = $true
    } catch {
      continue
    }
  }

  Start-Sleep -Milliseconds 350
} while ((Get-Date) -lt $deadline)

$refreshStatus = 'skipped'
if ($appliedHandles.Count -gt 0 -and
    -not [string]::IsNullOrWhiteSpace($pythonw) -and
    (Test-Path -LiteralPath $refreshScript -PathType Leaf)) {
  try {
    $refreshArguments = "`"$refreshScript`" " + (($appliedHandles.Keys | Sort-Object) -join ' ')
    $refreshProcess = Start-Process `
      -FilePath $pythonw `
      -ArgumentList $refreshArguments `
      -WindowStyle Hidden `
      -Wait `
      -PassThru
    $refreshStatus = "exit-$($refreshProcess.ExitCode)"
  } catch {
    $refreshStatus = 'error'
  }
}

try {
  $logDirectory = Split-Path -Parent $logPath
  if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
  }
  $status = if ($appliedHandles.Count -gt 0) { 'applied' } else { 'not-found' }
  Add-Content -LiteralPath $logPath -Encoding UTF8 -Value (
    '{0:yyyy-MM-dd HH:mm:ss} status={1} hwnds={2} appid={3} icon={4} refresh={5}' -f `
      (Get-Date), $status, (($appliedHandles.Keys | Sort-Object) -join ','), $appId, $iconPath, $refreshStatus
  )
} catch {
}

if ($appliedHandles.Count -eq 0) { exit 6 }
if ($refreshStatus -ne 'exit-0') { exit 7 }
exit 0

# SIG # Begin signature block
# MIIFqgYJKoZIhvcNAQcCoIIFmzCCBZcCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCBoOeaLD3M6j1Wv
# mIo3JWDHu1Su6i7Tbck4AtSj1i3MzKCCAxgwggMUMIIB/KADAgECAhAQTww58XhT
# r04Zt5EhTLnQMA0GCSqGSIb3DQEBCwUAMCIxIDAeBgNVBAMMF0dhc3RvbiBFQ0Qg
# Q29kZSBTaWduaW5nMB4XDTI2MDcwNDE1NTMwNVoXDTMxMDcwNDE2MDMwMlowIjEg
# MB4GA1UEAwwXR2FzdG9uIEVDRCBDb2RlIFNpZ25pbmcwggEiMA0GCSqGSIb3DQEB
# AQUAA4IBDwAwggEKAoIBAQDy8cgRHRycbJlXZ7OE7Q0ZFXtq3u5L04lNuoOL7KT4
# IN2Pvr6J21+eoKCJKc+s/UJejygI0nnXAAKKgfA8sMhLLCN++ofK6Op5HyAUf+DT
# kT79kPKmUkVGoZT9/9hxFNCoY8ByCMhW0gzSK42wx6/Vv95O9RNJtwu14T8FyKlS
# jdvEPg9ljkNi0MR2j6iNoCNzUoS+rDSgGQYDYfe+dgKEu3bCrjg4t33llr3y0CJh
# ZYgcP0YFWlRcxf6bkiYERWmepjid6CAEZxVaUWoE2tEc1n0FtlAGKzS1M3UUgF23
# 3/ZOHR/hzHybvisMaQRTbLthNHzyaRut0uVm4GdT8Ym5AgMBAAGjRjBEMA4GA1Ud
# DwEB/wQEAwIHgDATBgNVHSUEDDAKBggrBgEFBQcDAzAdBgNVHQ4EFgQUOrYj+qph
# 9Pw1d3HkfwBqesLw5DAwDQYJKoZIhvcNAQELBQADggEBAAGpurh7j5Sj5yuOSGuy
# 6XV7OUUfgMYhZObKNSHWq0vMzT/YQk5uasfPc1Rbzqq6KJ5I+P75mzvFtG/gxMWA
# 8qgMgfzEGz6jjKnfS4F6RymvfRRV4CYIM+Ar4gSt2LfktoN0BQM+R/Gx9BTiI3vI
# xteRvRqXkxzwiIDLy0bvWPRQ+PZbsEHtz3UaDQjzpBTtDILnRZ+LLfXDgp+wo5GD
# m/Fv5Q7lQ3qoBm/Y5m/PZPbCqlCYa+BzUwbrieahzq0N2CdFucL9Vfe7QziAmdLi
# DsO+KiKkSstCvIRqFVecxPqRF14eMaFjUM5L+eczualApo6gv4v6peEoO0+jnajh
# ALQxggHoMIIB5AIBATA2MCIxIDAeBgNVBAMMF0dhc3RvbiBFQ0QgQ29kZSBTaWdu
# aW5nAhAQTww58XhTr04Zt5EhTLnQMA0GCWCGSAFlAwQCAQUAoIGEMBgGCisGAQQB
# gjcCAQwxCjAIoAKAAKECgAAwGQYJKoZIhvcNAQkDMQwGCisGAQQBgjcCAQQwHAYK
# KwYBBAGCNwIBCzEOMAwGCisGAQQBgjcCARUwLwYJKoZIhvcNAQkEMSIEIFRMtUrA
# +KpVh9Zu2yWiVnK/uBCsjDRixr2rsVrt4socMA0GCSqGSIb3DQEBAQUABIIBABh/
# Kqt6ul+0w8mHN0s8hzh8Io4jj13Y2ujDyhjJA/Z3KgQN5XMNiBQHf5mIbM+Ko8dk
# lzdrMKJ+2OXE8u0e/8Llp2ARISeM8x3RE7Z9fiMSq/eFURB0KgG+uyYKK4MEXYii
# gBoS7PqIpbYa/JmGlfJN9fCd6/r4qWp1nfJ3LbGPqNNcn5i3EzhXpUACBL52e5HW
# +KwXlyc56ar6haWGI9qZgkb0LEE/8QGNYokVTHAmH2D1cucGxeZCoH2jUrWqNN26
# GFxMGeIAmM23oMOUIqTXC7iOP/HEjECjTbjcS1ponUZsX6J456phh8R3JbuH79rB
# mvmYn54G+bmi4a2LcE8=
# SIG # End signature block
