# 설치 파일 만들기: dist\HWP_GPT-Setup-<버전>.exe  (배포 전체는 packaging\release.py)
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -CodexDir spike\bin
# 버전은 src\hwpgpt\__init__.py의 __version__ (release.py가 올림)
param(
  [Parameter(Mandatory)] [string]$CodexDir,   # 공식 Codex 릴리스를 푼 폴더 (SHA256·서명 확인한 것)
  [string]$Python = ".\.venv\Scripts\python.exe"
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path src\hwpgpt\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$codexExe = Join-Path $CodexDir 'codex-x86_64-pc-windows-msvc.exe'
$sig = Get-AuthenticodeSignature $codexExe
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'OpenAI') { throw "Codex 서명 확인 실패: $($sig.Status)" }

& $Python -m PyInstaller packaging\hwpgpt.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE) { throw "PyInstaller 실패" }
$out = Join-Path $root 'dist\HWP_GPT'

# Codex는 필요한 것만 (음성 기능·중복 사본 제외). code-mode-host는 MCP 도구 호출에 필요 (2026-10-22 시험)
$cx = Join-Path $out 'codex'
New-Item -ItemType Directory -Force (Join-Path $cx 'codex-resources') | Out-Null
Copy-Item $codexExe, (Join-Path $CodexDir 'codex-package.json'), (Join-Path $CodexDir 'codex-code-mode-host.exe') $cx
Copy-Item (Join-Path $CodexDir 'codex-path') $cx -Recurse -Force
Copy-Item (Join-Path $CodexDir 'codex-resources\*.exe') (Join-Path $cx 'codex-resources')
Copy-Item packaging\THIRD_PARTY_NOTICES.md $out -Force

$env:HWPGPT_VERSION = $version
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /Q packaging\hwpgpt.iss
if ($LASTEXITCODE) { throw "ISCC 실패" }

$setup = Join-Path $root "dist\HWP_GPT-Setup-$version.exe"
"만듦: $setup ($([math]::Round((Get-Item $setup).Length/1MB)) MB)"
