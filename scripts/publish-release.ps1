<#
.SYNOPSIS
  生成小仓鼠桌宠的发布包 DesktopPet.zip 与 latest.json。

.DESCRIPTION
  参照 ChromeClick3.0 的 publish-release.ps1，但按桌宠形态做了两处关键改动：
   1. 用 Python + PyInstaller 打包，而不是 dotnet publish。
   2. 用户数据就在安装目录里，所以 zip 里的 config.json / pets.json 取自源码模板，
      state.json 写成空模板，绝不把本机用户设置发布到公开仓库。

  用法：
    .\scripts\publish-release.ps1
    .\scripts\publish-release.ps1 -Version v1.0.1 -Repo wAwBill/DesktopPet
    .\scripts\publish-release.ps1 -SkipBuild   # 复用已有交付目录，仅重新生成清单
#>
param(
    [string]$Version = "",
    [string]$Repo = "",
    [string]$OutDir = "",
    [string]$StageDir = "",
    [string]$Python = "python",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Read-JsonFile([string]$path) {
    if (-not (Test-Path $path)) { throw "找不到 $path" }
    return (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

# ---- 版本：唯一来源是 version.json
$vmeta = Read-JsonFile (Join-Path $root "version.json")
$appVersion = [string]$vmeta.version
$appName = [string]$vmeta.name
$zipName = [string]$vmeta.zip
if ([string]::IsNullOrWhiteSpace($zipName)) { $zipName = "DesktopPet.zip" }

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $appVersion
} else {
    $Version = ($Version.Trim() -replace '^[vV]', '')
    if ($Version -ne $appVersion) {
        throw "tag 版本 $Version 与 version.json 的 $appVersion 不一致。发版前请先改 version.json。"
    }
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "版本号格式无效：$Version（应为 1.0.0 或 v1.0.0）"
}

# ---- 更新日志：必须是本版客户能看懂的内容
$notesPath = Join-Path $root "Docs\发布\本版更新说明.txt"
if (-not (Test-Path $notesPath)) { throw "找不到 $notesPath" }
$notes = (Get-Content $notesPath -Raw -Encoding UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($notes) -or $notes -match 'TODO|示例|在此填写') {
    throw "本版更新说明.txt 不能为空，也不能留模板套话。"
}

# ---- 更新源仓库
if ([string]::IsNullOrWhiteSpace($Repo)) {
    $umeta = Read-JsonFile (Join-Path $root "update.json")
    $Repo = [string]$umeta.repo
}
# 发布包必须带正式更新源，否则新用户解压后 repo 为空，自动更新会静默失效
if ([string]::IsNullOrWhiteSpace($Repo) -or $Repo -notmatch '^[\w.-]+/[\w.-]+$') {
    throw "发版必须指定更新源仓库（-Repo owner/repo，或 update.json 的 repo）"
}

# ---- 输出目录
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Join-Path $root "publish" }
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
if ([string]::IsNullOrWhiteSpace($StageDir)) { $StageDir = Join-Path $OutDir "app" }
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

# ---- 打包主程序（exe + 外置资源）
if (-not $SkipBuild) {
    Write-Host "PyInstaller 打包 $appVersion ..."
    # PyInstaller 把进度日志写 stderr；PowerShell 5.1 在输出被重定向时会把它
    # 包成 ErrorRecord，配合 Stop 会误判为失败。调用期间临时降级为 Continue。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python (Join-Path $root "scripts\build.py") $root --name "小仓鼠桌宠" --out $StageDir
    $buildExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($buildExit -ne 0) { throw "PyInstaller 打包失败（解释器：$Python）" }
} elseif (-not (Test-Path (Join-Path $StageDir "小仓鼠桌宠.exe"))) {
    throw "-SkipBuild 需要 $StageDir 里已有打包好的 exe"
}

# ---- 用干净模板替换用户数据（绝不公开本机设置）
$configSrc = Join-Path $root "config.json"
$petsSrc = Join-Path $root "pets.json"
Copy-Item $configSrc (Join-Path $StageDir "config.json") -Force
Copy-Item $petsSrc (Join-Path $StageDir "pets.json") -Force

$stateTemplate = @'
{
  "date": "",
  "water": 0,
  "quota_used": 0,
  "affection": 0,
  "todos": [],
  "panel_x": null,
  "panel_y": null,
  "boat_prev_pet": ""
}
'@
Set-Content -Path (Join-Path $StageDir "state.json") -Value $stateTemplate -Encoding UTF8

# 兜底：把 version.json / update.json / updater.py / README.md 补齐
foreach ($f in @("version.json", "update.json", "updater.py", "README.md")) {
    $src = Join-Path $root $f
    if ((Test-Path $src) -and -not (Test-Path (Join-Path $StageDir $f))) {
        Copy-Item $src (Join-Path $StageDir $f) -Force
    }
}

# 发布包必须自带正式更新源：新用户解压后自动更新才会生效。
# 以 -Repo 参数为准，不依赖源文件里恰好填了什么。
$stagedUpdate = Join-Path $StageDir "update.json"
$u = Read-JsonFile $stagedUpdate
$u.repo = $Repo
$u | ConvertTo-Json -Depth 4 | Set-Content -Path $stagedUpdate -Encoding UTF8

# 打包前校验：主程序必须在，用户数据不能带真实值
$must = @("小仓鼠桌宠.exe", "pet.py", "boat_fx.py", "updater.py",
          "version.json", "update.json", "config.json", "pets.json",
          "state.json", "使用说明.txt")
foreach ($f in $must) {
    if (-not (Test-Path (Join-Path $StageDir $f))) { throw "发布目录缺少 $f" }
}
$stagedVersion = (Read-JsonFile (Join-Path $StageDir "version.json")).version
if ([string]$stagedVersion -ne $Version) { throw "发布包内版本号 $stagedVersion 与 $Version 不一致" }
$stagedRepo = [string](Read-JsonFile $stagedUpdate).repo
if ($stagedRepo -ne $Repo) { throw "发布包内更新源 $stagedRepo 与 $Repo 不一致" }

# ---- 生成 zip（文件名必须英文，否则 GitHub 会收成 default.zip）
$zipPath = Join-Path $OutDir $zipName
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
try {
    [System.IO.Compression.ZipFile]::CreateFromDirectory($StageDir, $zipPath)
} catch {
    Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $zipPath -Force
}
if (-not (Test-Path $zipPath)) { throw "生成 $zipName 失败" }

# ---- 生成 latest.json
$downloadUrl = ""
if (-not [string]::IsNullOrWhiteSpace($Repo)) {
    $downloadUrl = "https://github.com/$Repo/releases/download/v$Version/$zipName"
}
$latest = [ordered]@{
    version  = $Version
    name     = $appName
    zip      = $zipName
    url      = $downloadUrl
    runtime  = "win-x64"
    notes    = $notes
}
$latest | ConvertTo-Json -Depth 4 |
    Set-Content -Path (Join-Path $OutDir "latest.json") -Encoding UTF8

Write-Host ""
Write-Host "已生成："
Write-Host "  $zipPath  ($([math]::Round((Get-Item $zipPath).Length / 1MB, 1)) MB)"
Write-Host "  $(Join-Path $OutDir 'latest.json')"
Write-Host "  version = $Version"
Write-Host "  url     = $downloadUrl"
Write-Host ""
Write-Host "打 tag 后 Actions 会重新执行本脚本并上传 Release："
Write-Host "  git tag v$Version; git push origin v$Version"
