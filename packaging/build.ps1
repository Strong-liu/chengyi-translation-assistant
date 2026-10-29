param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$RuntimeSource = $env:CHENGYI_RUNTIME_SOURCE,
    [string]$DependencySource = $env:CHENGYI_DEPENDENCY_SOURCE,
    [string]$EngineSource = (Join-Path $ProjectRoot 'engine'),
    [string]$AssetsSource = $env:CHENGYI_ASSETS_SOURCE,
    [string]$Compiler = $env:CHENGYI_INNO_COMPILER,
    [string]$VcRuntimeSource = $env:CHENGYI_VC_RUNTIME_SOURCE,
    [string]$IconSource = (Join-Path $ProjectRoot 'assets\branding\app.ico'),
    [switch]$PrepareOnly,
    [switch]$SkipPrepare
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONNOUSERSITE = '1'
$taskPayload = Join-Path $ProjectRoot 'build\payload'
$taskOutput = Join-Path $ProjectRoot 'dist'
$taskRuntime = Join-Path $taskPayload 'runtime'
if (-not $RuntimeSource) { $RuntimeSource = Join-Path $PSScriptRoot 'deps\python' }
if (-not $DependencySource) { $DependencySource = Join-Path $ProjectRoot '.venv\Lib\site-packages' }
if (-not $AssetsSource) { $AssetsSource = Join-Path $PSScriptRoot 'deps\babeldoc' }
if (-not $VcRuntimeSource) {
    $VcRuntimeSource = Join-Path $PSScriptRoot 'deps\vc-app-local'
    if (-not (Test-Path -LiteralPath $VcRuntimeSource)) { $VcRuntimeSource = Join-Path $PSScriptRoot 'toolchain\vc-app-local' }
}
if (-not $Compiler) {
    $Compiler = Join-Path $PSScriptRoot 'toolchain\inno-6.4.3\{app}\ISCC.exe'
    if (-not (Test-Path -LiteralPath $Compiler)) {
        $taskCompilerCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($taskCompilerCommand) { $Compiler = $taskCompilerCommand.Source }
    }
}

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$ExtraArgs = @()) {
    if (-not (Test-Path -LiteralPath $Source)) { throw "Missing input: $Source" }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy.exe $Source $Destination /E /R:2 /W:1 /NFL /NDL /NJH /NJS @ExtraArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copy failed: $Source -> $Destination (robocopy $LASTEXITCODE)" }
}

New-Item -ItemType Directory -Force -Path $taskPayload,$taskOutput | Out-Null
if (-not $SkipPrepare) {
    Copy-Tree $RuntimeSource $taskRuntime @('/XD','__pycache__','test','tests')
    Copy-Tree $DependencySource (Join-Path $taskRuntime 'Lib\site-packages') @('/XD','__pycache__','tests','test','pip','ruff','/XF','*.pyc','*.pth','_virtualenv.py')
    foreach ($folder in @('fonts','models','cmap','tiktoken')) {
        Copy-Tree (Join-Path $AssetsSource $folder) (Join-Path $taskPayload "assets\$folder")
    }
    Copy-Item -LiteralPath (Join-Path $RuntimeSource 'LICENSE.txt') -Destination (Join-Path $taskPayload 'PYTHON_LICENSE.txt') -Force
}
Copy-Tree (Join-Path $EngineSource 'pdf2zh_next') (Join-Path $taskPayload 'engine\pdf2zh_next') @('/XD','__pycache__','/XF','*.pyc')
Copy-Item -LiteralPath (Join-Path $EngineSource 'LICENSE'),(Join-Path $EngineSource 'pyproject.toml') -Destination (Join-Path $taskPayload 'engine') -Force
& (Join-Path $taskRuntime 'python.exe') (Join-Path $PSScriptRoot 'patch_runtime.py') (Join-Path $taskRuntime 'Lib\site-packages')
if ($LASTEXITCODE -ne 0) { throw 'Failed to apply the pinned BabelDOC compatibility patches.' }

$taskVcDirectory = $VcRuntimeSource
if (Test-Path -LiteralPath $taskVcDirectory) {
    Get-ChildItem -LiteralPath $taskVcDirectory -Filter '*.dll' -File | ForEach-Object {
        $taskDllTarget = Join-Path $taskRuntime $_.Name
        if (-not (Test-Path -LiteralPath $taskDllTarget) -or (Get-FileHash -LiteralPath $_.FullName).Hash -ne (Get-FileHash -LiteralPath $taskDllTarget).Hash) {
            Copy-Item -LiteralPath $_.FullName -Destination $taskRuntime -Force
        }
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'licenses\Microsoft-VC-Redistributable-License.rtf') -Destination (Join-Path $taskPayload 'MICROSOFT_VC_RUNTIME_LICENSE.rtf') -Force
}
elseif (-not $SkipPrepare) { throw 'Provide the official Microsoft app-local runtime folder with -VcRuntimeSource or CHENGYI_VC_RUNTIME_SOURCE.' }
& (Join-Path $taskRuntime 'python.exe') (Join-Path $PSScriptRoot 'collect_font_licenses.py') $taskPayload
if ($LASTEXITCODE -ne 0) { throw 'Failed to collect bundled font licenses.' }

$taskCsc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $taskCsc)) { throw 'The .NET Framework C# compiler was not found.' }
$taskLauncher = Join-Path $taskPayload 'PaperTranslator.exe'
$taskCompilerArguments = @('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001','/reference:System.Windows.Forms.dll','/reference:System.Management.dll',"/out:$taskLauncher")
if (Test-Path -LiteralPath $IconSource) {
    if ([IO.Path]::GetExtension($IconSource).ToLowerInvariant() -ne '.ico') { throw 'IconSource must be an ICO file. Convert the original with packaging/make_icon.py first.' }
    $taskBranding = Join-Path $taskPayload 'assets\branding'
    New-Item -ItemType Directory -Force -Path $taskBranding | Out-Null
    $taskIcon = Join-Path $taskBranding 'app.ico'
    Copy-Item -LiteralPath $IconSource -Destination $taskIcon -Force
    $taskCompilerArguments += "/win32icon:$taskIcon"
}
& $taskCsc @taskCompilerArguments (Join-Path $PSScriptRoot 'PaperTranslatorLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Failed to compile the desktop launcher.' }
if ($PrepareOnly) {
    Write-Output "Prepared portable runtime and assets: $taskPayload"
    exit 0
}

foreach ($file in @('app.py','INSTALLATION_NOTES.txt','LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $file) -Destination (Join-Path $taskPayload $file) -Force
}
Copy-Tree (Join-Path $ProjectRoot 'static') (Join-Path $taskPayload 'static') @('/XD','__pycache__','/XF','*.pyc')
$taskSupport = Join-Path $taskPayload 'engine_support'
New-Item -ItemType Directory -Force -Path $taskSupport | Out-Null
foreach ($file in @('__init__.py','baidu_academic.py','run_engine.py','term_protection.py','README.md')) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "engine_support\$file") -Destination (Join-Path $taskSupport $file) -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD_PARTY_NOTICES.md') -Destination $taskPayload -Force
$taskBuildSource = Join-Path $taskPayload 'build_source'
New-Item -ItemType Directory -Force -Path $taskBuildSource | Out-Null
foreach ($file in @('PaperTranslatorLauncher.cs','PaperTranslator.iss','build.ps1','collect_font_licenses.py','patch_runtime.py','make_icon.py','README.md')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $taskBuildSource -Force
}
Copy-Tree (Join-Path $PSScriptRoot 'patches') (Join-Path $taskBuildSource 'patches')
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'requirements-lock.txt') -Destination $taskBuildSource -Force
$taskLicenses = Join-Path $taskPayload 'THIRD_PARTY_LICENSES'
New-Item -ItemType Directory -Force -Path $taskLicenses | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'licenses\SIL-OFL-1.1.txt') -Destination $taskLicenses -Force
Copy-Item -LiteralPath (Join-Path $taskPayload 'engine\LICENSE') -Destination (Join-Path $taskLicenses 'PDFMathTranslate-AGPL-3.0.txt') -Force
Copy-Item -LiteralPath (Join-Path $taskPayload 'FONT_LICENSES.txt') -Destination $taskLicenses -Force
foreach ($metadata in (Get-ChildItem -LiteralPath (Join-Path $taskRuntime 'Lib\site-packages') -Directory -Filter '*.dist-info')) {
    $taskPackageLicense = Join-Path $metadata.FullName 'licenses'
    if (Test-Path -LiteralPath $taskPackageLicense) {
        Copy-Tree $taskPackageLicense (Join-Path $taskLicenses $metadata.Name)
    }
}
if (-not (Test-Path -LiteralPath $Compiler)) { throw "Inno Setup compiler not found: $Compiler" }
& $Compiler "/DPayloadDir=$taskPayload" "/DOutputDir=$taskOutput" (Join-Path $PSScriptRoot 'PaperTranslator.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
Get-ChildItem -LiteralPath $taskOutput -Filter '*Setup.exe' | ForEach-Object {
    Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
}
