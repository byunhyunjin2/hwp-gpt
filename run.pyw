"""HWP_GPT 패널 실행 (콘솔 창 없음). pythonw.exe로 실행: .venv\\Scripts\\pythonw.exe run.pyw"""
import os
import subprocess
import sys
from pathlib import Path

# python.exe로 실행되면 검은 콘솔 창이 남으므로 pythonw.exe로 다시 띄우고 끝낸다
if os.name == "nt" and Path(sys.executable).name.lower() == "python.exe":
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if pyw.exists():
        subprocess.Popen([str(pyw), str(Path(__file__).resolve()), *sys.argv[1:]],
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from hwpgpt.app import main

main()
