# 把独立可执行文件构建到 dist\ 目录。
#
#   .\build.ps1
#
# 产物：
#   dist\autolevel-gui.exe   窗口版，可直接双击
#   dist\autolevel.exe       控制台版，即命令行界面
#
# 两者都是 onefile 打包，目标机器无需安装 Python。

# 这里刻意不写 "Stop"：PyInstaller 会把进度日志写到 stderr，而在 Windows
# PowerShell 5.1 下那会被提升为终止性错误，即使构建完全成功。因此改为显式
# 检查退出码。
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

# PyInstaller 只能分析项目自己的 venv。桌面终端和 agent 宿主可能通过
# PYTHONPATH 注入无关环境；那些模块并不随 AutoLevel 发布，会让 hook 发现
# 失败或污染打包内容。
$env:PYTHONPATH = ""

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "未找到虚拟环境。请先运行：uv venv --python 3.11 .venv"
    exit 1
}

# 正在运行的实例会锁住 dist\*.exe，而 PyInstaller 只会报一句 "拒绝访问"，
# 看起来像权限问题。
$running = Get-Process -Name "autolevel*" -ErrorAction SilentlyContinue
if ($running) {
    Write-Error ("autolevel 正在运行（PID " + ($running.Id -join ", ") +
        "）。请从托盘退出，或执行：Get-Process autolevel* | Stop-Process -Force")
    exit 1
}

Write-Host "`n=== 生成图标 ===" -ForegroundColor Cyan
& $python packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { Write-Error "图标生成失败"; exit 1 }

$common = @(
    "--noconfirm",
    "--onefile",
    "--paths", "src",
    "--icon", "packaging\autolevel.ico",
    # pycaw 是手写声明 COM 接口的，其子模块导入又足够延迟，没有这项
    # PyInstaller 会漏掉它们。
    "--collect-all", "pycaw",
    "--collect-all", "comtypes",
    # winsdk 带有编译好的 WinRT 投影模块，运行时按名称导入，
    # 因此 PyInstaller 无法通过静态分析发现。
    "--collect-all", "winsdk"
)

Write-Host "`n=== 构建 autolevel-gui.exe（窗口版）===" -ForegroundColor Cyan
& $python -m PyInstaller @common --windowed --name autolevel-gui packaging\gui_entry.py
if ($LASTEXITCODE -ne 0) { Write-Error "GUI 构建失败"; exit 1 }

Write-Host "`n=== 构建 autolevel.exe（控制台版）===" -ForegroundColor Cyan
& $python -m PyInstaller @common --console --name autolevel packaging\cli_entry.py
if ($LASTEXITCODE -ne 0) { Write-Error "CLI 构建失败"; exit 1 }

Write-Host "`n构建完成：" -ForegroundColor Green
Get-ChildItem dist\*.exe | ForEach-Object {
    "  {0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)
}
