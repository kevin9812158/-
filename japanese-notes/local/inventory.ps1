# 電腦環境盤點（只讀取，不安裝、不修改任何東西）
# 用法：雙擊 盤點電腦環境.bat，結果存在同資料夾的 inventory.txt，把內容貼給 Claude。

$ErrorActionPreference = 'SilentlyContinue'
$out = Join-Path $PSScriptRoot 'inventory.txt'
$lines = New-Object System.Collections.Generic.List[string]
function Add($s) { $lines.Add([string]$s) }
function Section($t) { Add ''; Add "=== $t ===" }
function Cmd($name, $cmdArgs) {
    $c = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $c) { Add "${name}：沒有找到"; return }
    Add "${name}：$($c.Source)"
    if ($cmdArgs) {
        $v = & $c.Source @cmdArgs 2>&1 | Select-Object -First 3
        foreach ($x in $v) { Add "    $x" }
    }
}

Add "盤點時間：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

Section '系統'
$os = Get-CimInstance Win32_OperatingSystem
Add "Windows：$($os.Caption) $($os.Version)（$($os.OSArchitecture)）"
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Add "CPU：$($cpu.Name)（$($cpu.NumberOfCores) 核 / $($cpu.NumberOfLogicalProcessors) 執行緒）"
Add ("記憶體：{0:N1} GB" -f ($os.TotalVisibleMemorySize / 1MB))
Get-CimInstance Win32_VideoController | ForEach-Object { Add "顯示卡：$($_.Name)" }
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object {
    Add ("磁碟 {0}: 可用 {1:N1} GB / 共 {2:N1} GB" -f $_.Name, ($_.Free / 1GB), (($_.Used + $_.Free) / 1GB))
}
Add "目前資料夾：$PSScriptRoot"

Section '開發工具'
Cmd 'uv' @('--version')
Cmd 'python' @('--version')
Cmd 'py' @('--version')
Cmd 'git' @('--version')
Cmd 'ffmpeg' @('-version')
Cmd 'ffprobe' @('-version')
Cmd 'claude' @('--version')
Cmd 'node' @('--version')
Cmd 'conda' @('--version')
Cmd 'winget' @('--version')
Cmd 'nvidia-smi' @('--query-gpu=name,driver_version,memory.total', '--format=csv,noheader')

Section '所有 Python 直譯器'
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { & py -0p 2>&1 | ForEach-Object { Add "  $_" } } else { Add '  （沒有 py 啟動器）' }
$uvc = Get-Command uv -ErrorAction SilentlyContinue
if ($uvc) { Add '  uv 管理的 Python：'; & uv python list --only-installed 2>&1 | ForEach-Object { Add "    $_" } }
Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { Add "  PATH 上的 python：$($_.Source)" }

Section '本專案會用到的套件（在 PATH 上第一個 python 裡）'
$p = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
if ($p -and $p.Source -notlike '*WindowsApps*') {
    $pkgs = 'sherpa-onnx','soundfile','numpy','scipy','rapidfuzz','pykakasi','python-docx','onnxruntime','torch'
    foreach ($k in $pkgs) {
        $v = & $p.Source -m pip show $k 2>$null | Select-String '^Version:'
        if ($v) { Add "  $k $($v.ToString().Split(':')[1].Trim())" } else { Add "  ${k}：未安裝" }
    }
} else { Add '  （沒有可用的 python，或只有 Microsoft Store 的捷徑）' }

Section '網路代理設定（影響下載模型）'
Add "HTTPS_PROXY=$env:HTTPS_PROXY"
Add "HTTP_PROXY=$env:HTTP_PROXY"
$ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
Add "系統代理：ProxyEnable=$($ie.ProxyEnable) ProxyServer=$($ie.ProxyServer)"

Section '本專案資料夾現況'
$here = $PSScriptRoot
foreach ($d in '.venv','models','lessons') {
    $p2 = Join-Path $here $d
    if (Test-Path $p2) { Add "  ${d}：已存在" } else { Add "  ${d}：尚未建立" }
}

$lines | Out-File -FilePath $out -Encoding utf8
$lines | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host "已存到：$out（沒有安裝或修改任何東西）"
