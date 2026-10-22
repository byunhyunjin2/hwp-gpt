# PyInstaller: pyinstaller packaging/hwpgpt.spec --noconfirm
# 결과: dist/HWP_GPT/{HWP_GPT.exe, hwpgpt-tools.exe, _internal/}  (codex/는 build.ps1이 복사)
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
datas = [
    (str(SRC / "hwpgpt" / "ui"), "hwpgpt/ui"),
    (str(SRC / "hwpgpt" / "assets"), "hwpgpt/assets"),
]

app = Analysis([str(ROOT / "run.pyw")], pathex=[str(SRC)], datas=datas,
               hiddenimports=["hwpgpt.app", "win32timezone"])
tools = Analysis([str(ROOT / "packaging" / "tools_entry.py")], pathex=[str(SRC)],
                 hiddenimports=["hwpgpt.tools_server", "win32timezone"])

ICON = str(SRC / "hwpgpt" / "assets" / "hwpgpt.ico")  # 문서 위 병아리 (packaging/make_icon.py)
app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="HWP_GPT",
              console=False, upx=False, icon=ICON)
tools_exe = EXE(PYZ(tools.pure), tools.scripts, [], exclude_binaries=True, name="hwpgpt-tools",
                console=True, upx=False, icon=ICON)

COLLECT(app_exe, app.binaries, app.datas, tools_exe, tools.binaries, tools.datas,
        name="HWP_GPT", upx=False)
