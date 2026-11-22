# Cephe setup, run by Install.bat. Safe to run again: everything already in place is skipped.
param([switch]$Yes, [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root 'runtime'
$PortableUrl = 'https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z'

function Say($m) { Write-Host $m }
function AskYes($q) {
    if ($Yes) { return $true }
    $a = Read-Host "$q (Y/n)"
    return ($a -eq '' -or $a -match '^[yY]')
}
function Fail($m) { Say ""; Say "ERROR: $m"; exit 1 }

Say ''
Say '==========================================='
Say '  Cephe setup'
Say '==========================================='

# ---- 1. graphics card ---------------------------------------------------------------------------------
Say ''
Say '[1/5] Graphics card'
$gpu = $null
try { $gpu = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1 } catch {}
if (-not $gpu) {
    Say '  No NVIDIA graphics card found. Rendering needs an NVIDIA card with at least 6 GB of memory.'
    if (-not (AskYes '  Continue anyway?')) { exit 1 }
} else {
    $parts = $gpu.Split(',')
    $mem = [int]($parts[1].Trim())
    Say "  $($parts[0].Trim()), $([math]::Round($mem / 1024, 1)) GB"
    if ($mem -lt 5800) {
        Say '  WARNING: with less than 6 GB, rendering may be very slow or run out of memory.'
        if (-not (AskYes '  Continue anyway?')) { exit 1 }
    }
}

# ---- 2. ComfyUI (render engine) -----------------------------------------------------------------------
Say ''
Say '[2/5] Render engine (ComfyUI)'
$comfyPython = $null; $comfyCwd = $null; $comfyCmd = $null; $modelsDir = $null; $portable = $false

# a) is Comfy Desktop installed?
$desk = Join-Path $env:LOCALAPPDATA 'Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI'
$deskPy = Join-Path $desk '.venv\Scripts\python.exe'
if ((Test-Path (Join-Path $desk 'main.py')) -and (Test-Path $deskPy)) {
    $yaml = Get-ChildItem (Join-Path $env:APPDATA 'Comfy Desktop\instance-model-paths\*.yaml') -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $shared = Join-Path $env:LOCALAPPDATA 'Comfy-Desktop\ComfyUI-Shared'
    $comfyPython = $deskPy; $comfyCwd = $desk
    $comfyCmd = @($deskPy, 'main.py', '--port', '8188')
    if ($yaml) {
        $comfyCmd += @('--extra-model-paths-config', $yaml.FullName)
        $m = Select-String -Path $yaml.FullName -Pattern '^(?!\s*#)\s*base_path:\s*(.+)$' | Select-Object -First 1
        if ($m) { $modelsDir = Join-Path ($m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")) 'models' }
        if ($modelsDir -and -not (Test-Path $modelsDir)) { $modelsDir = $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'") }
    }
    if (Test-Path $shared) { $comfyCmd += @('--output-directory', (Join-Path $shared 'output'), '--input-directory', (Join-Path $shared 'input')) }
    if (-not $modelsDir) { $modelsDir = Join-Path $desk 'models' }
    Say "  Found Comfy Desktop: $desk"
}

# b) a portable build downloaded earlier, else download it
$portableDir = Join-Path $Runtime 'ComfyUI_windows_portable'
if (-not $comfyPython) {
    if (-not (Test-Path (Join-Path $portableDir 'ComfyUI\main.py'))) {
        Say '  ComfyUI not found on this computer. The official portable build will be downloaded (~2 GB, github.com).'
        if (-not (AskYes '  Download it?')) { Fail 'The app cannot work without the render engine.' }
        New-Item -ItemType Directory -Force $Runtime | Out-Null
        $archive = Join-Path $Runtime 'comfyui_portable.7z'
        & curl.exe -L -C - --fail --retry 5 -o $archive $PortableUrl
        if ($LASTEXITCODE -ne 0) { Fail 'ComfyUI could not be downloaded. Run setup again; it resumes where it stopped.' }
        Say '  Unpacking ...'
        & tar.exe -xf $archive -C $Runtime
        if ($LASTEXITCODE -ne 0) { Fail 'Could not unpack the archive (needs Windows 11). Unpack it with 7-Zip into the runtime folder.' }
        Remove-Item $archive -Force
    }
    $comfyPython = Join-Path $portableDir 'python_embeded\python.exe'
    $comfyCwd = $portableDir
    $comfyCmd = @($comfyPython, '-s', 'ComfyUI\main.py', '--windows-standalone-build', '--port', '8188')
    $modelsDir = Join-Path $portableDir 'ComfyUI\models'
    $portable = $true
    Say "  Portable ComfyUI: $portableDir"
}

# ---- ODA File Converter (to read DWG) -------------------------------------------------------------
$oda = Get-ChildItem 'C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $oda) {
    Say ''
    Say '  Reading DWG files needs the free ODA File Converter (Open Design Alliance).'
    Say '  Installing it means accepting the ODA license terms: https://www.opendesign.com/guestfiles'
    if (AskYes '  Install ODA File Converter (I accept its license)?') {
        & winget install --id ODA.ODAFileConverter -e --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Say '  ODA could not be installed. You can use DXF files instead of DWG.' }
    } else {
        Say '  Skipped. You can use DXF files instead of DWG; run setup again to add ODA.'
    }
}

# ---- 3-4. app environment, models, settings (Python) ---------------------------------------------------
# Windows PowerShell strips the quotes of a JSON argument passed to a program, so hand it over in a file
New-Item -ItemType Directory -Force $Runtime | Out-Null
$cmdFile = Join-Path $Runtime 'comfy_cmd.json'
[IO.File]::WriteAllText($cmdFile, (ConvertTo-Json -Compress -InputObject @($comfyCmd)), (New-Object Text.UTF8Encoding $false))
$args2 = @((Join-Path $PSScriptRoot 'setup.py'), '--comfy-python', $comfyPython, '--comfy-cwd', $comfyCwd,
           '--comfy-cmd-file', $cmdFile, '--models-dir', $modelsDir)
if ($portable) { $args2 += '--portable' }
if ($Yes) { $args2 += '--yes' }
& $comfyPython @args2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- 5. desktop shortcut ---------------------------------------------------------------------------
Say ''
Say '[5/5] Desktop shortcut'
if (-not $NoShortcut) {
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Cephe.lnk'
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = Join-Path $Root 'Start.bat'
$s.WorkingDirectory = $Root
$s.WindowStyle = 7
$s.Description = 'Presentation renders from DWG elevations'
$s.Save()
Say "  $lnk"
}
Say ''
Say 'Setup complete. Start it with the "Cephe" shortcut on your desktop.'
