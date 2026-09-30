<#
.SYNOPSIS
  Capti Android Release-APK per ADB auf verbundenem Geraet installieren.

.DESCRIPTION
  Findet automatisch mobile/build/app/outputs/flutter-apk/app-release.apk
  relativ zum Skript-Ort (funktioniert aus jedem PowerShell-Verzeichnis).
  Prueft adb.exe, APK, adb devices und installiert mit "adb install -r".

.PARAMETER Build
  Vorher "flutter build apk --release" im mobile-Verzeichnis ausfuehren.

.PARAMETER AdbPath
  Pfad zu adb.exe. Default: C:\Users\divo9\Downloads\scrcpy-win64-v4.1\scrcpy-win64-v4.1\adb.exe
  Falls nicht vorhanden, wird automatisch "adb" aus PATH versucht (inkl. Suche in Downloads/scrcpy-*\*\adb.exe).

.EXAMPLE
  .\install_android.ps1
  .\install_android.ps1 -Build
  .\install_android.ps1 -AdbPath "C:\platform-tools\adb.exe" -Build
#>
[CmdletBinding()]
param(
  [switch]$Build,
  [string]$AdbPath = "C:\Users\divo9\Downloads\scrcpy-win64-v4.1\scrcpy-win64-v4.1\adb.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Pfade robust relativ zum Skript ---
if (-not $PSScriptRoot) { $PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ToolsDir  = $PSScriptRoot
$MobileDir = Resolve-Path (Join-Path $ToolsDir "..") -ErrorAction Stop | Select-Object -ExpandProperty Path
$ApkPath   = Join-Path $MobileDir "build\app\outputs\flutter-apk\app-release.apk"

function Fail($msg) {
  Write-Host "ERROR: $msg" -ForegroundColor Red
  exit 1
}
function Info($msg) { Write-Host $msg -ForegroundColor Cyan }
function Ok($msg)   { Write-Host $msg -ForegroundColor Green }

# --- 1) ADB aufloesen ---
$adb = $null
if (Test-Path -LiteralPath $AdbPath) {
  $adb = (Resolve-Path -LiteralPath $AdbPath).Path
} else {
  # Fallback: suche scrcpy-Versionen (v4.0/v4.1 etc.)
  $alt = Get-ChildItem -Path "C:\Users\divo9\Downloads\scrcpy-win64-*\*\adb.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($alt) {
    $adb = $alt.FullName
    Info ("Hinweis: Default-AdbPath nicht gefunden, nutze gefunden: " + $adb)
  } else {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) {
      $adb = $cmd.Source
      Info ("Hinweis: Default-AdbPath nicht gefunden, nutze PATH: " + $adb)
    }
  }
}
if (-not $adb -or -not (Test-Path -LiteralPath $adb)) {
  Fail ("adb.exe nicht gefunden.`n  Erwartet: " + $AdbPath + "`n  Tipp: scrcpy entpacken oder -AdbPath angeben / adb zu PATH hinzufuegen.`n  Gesucht: C:\Users\divo9\Downloads\scrcpy-win64-*\*\adb.exe und PATH")
}
Info ("ADB: " + $adb)
Info ("Mobile: " + $MobileDir)
Info ("APK : " + $ApkPath)

# --- 2) Optional Build ---
if ($Build) {
  $flutter = Get-Command flutter -ErrorAction SilentlyContinue
  if (-not $flutter) { Fail "'flutter' nicht im PATH. Flutter SDK installieren / PATH setzen." }
  Info "Build: flutter build apk --release (kann 1-2 Min dauern) ..."
  Push-Location $MobileDir
  try {
    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & flutter build apk --release 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldEAP
    if ($code -ne 0) { Fail ("flutter build fehlgeschlagen (Exit " + $code + ").") }
  } finally { Pop-Location }
  Info "Build abgeschlossen."
}

# --- 3) APK pruefen ---
if (-not (Test-Path -LiteralPath $ApkPath)) {
  Fail ("APK nicht gefunden: " + $ApkPath + "`n  Erst bauen:  .\install_android.ps1 -Build`n  oder:      flutter build apk --release  (in " + $MobileDir + ")")
}
$sizeMB = [math]::Round((Get-Item -LiteralPath $ApkPath).Length / 1MB, 1)
Info ("APK gefunden: " + $sizeMB + " MB")

# --- 4) adb devices ---
Info ("Pruefe verbundene Geraete: " + $adb + " devices")
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$devOutRaw = & $adb devices 2>&1
$devCode = $LASTEXITCODE
$ErrorActionPreference = $oldEAP
$devOut = ($devOutRaw | Out-String)
if ($devCode -ne 0) { Fail ("adb devices fehlgeschlagen:`n" + $devOut) }
Write-Host $devOut

# Parsen: nur Zeilen mit Geraet im Status "device"
$lines   = @(($devOut -split "`r?`n") | Where-Object { $_ -match '^\S+\s+device\s*$' })
$unauth  = @(($devOut -split "`r?`n") | Where-Object { $_ -match 'unauthorized' })
$offline = @(($devOut -split "`r?`n") | Where-Object { $_ -match 'offline' })

if ($unauth.Count -gt 0) {
  Fail "Geraet 'unauthorized' - am Handy USB-Debugging bestaetigen (RSA-Dialog) und erneut versuchen."
}
if ($lines.Count -eq 0) {
  if ($offline.Count -gt 0) { Fail "Geraet ist 'offline' - Kabel neu verbinden / USB-Debugging neu aktivieren." }
  Fail "Kein autorisiertes Geraet gefunden. Handy per USB verbinden, USB-Debugging aktivieren, Geraet entsperren."
}
if ($lines.Count -gt 1) {
  Info "Mehrere Geraete gefunden - installiere auf erstem (bei mehreren ggf. -s DEVICE_ID noetig). Geraete:"
  $lines | ForEach-Object { Write-Host ("  " + $_) }
} else {
  Info ("Geraet: " + $lines[0].Trim())
}

# --- 5) Install ---
Info ("Installiere: " + $adb + " install -r " + $ApkPath)
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$installOutRaw = & $adb install -r $ApkPath 2>&1
$installCode = $LASTEXITCODE
$ErrorActionPreference = $oldEAP
$installOut = ($installOutRaw | Out-String)
Write-Host $installOut
if ($installCode -ne 0) {
  Fail ("Installation fehlgeschlagen (Exit " + $installCode + ").`n" + $installOut)
}
if ($installOut -match 'Success') {
  Ok "SUCCESS: APK erfolgreich installiert."
  Ok ("APK: " + $ApkPath + " (" + $sizeMB + " MB) - Datei wurde NICHT geloescht.")
  exit 0
}
if ($installOut -match 'Failure') {
  Fail ("Installation meldet Failure:`n" + $installOut)
}
# Fallback: kein explizites Success, aber Exit 0
Ok "SUCCESS: adb install beendet (Exit 0). Pruefe Geraet."
exit 0
