"""Build only the Linux port's helper, atomically replacing the finished binary."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
compiler=shutil.which(os.environ.get('CXX','x86_64-w64-mingw32-g++'))
if not compiler:raise SystemExit('Install mingw-w64-gcc or set CXX.')
with tempfile.TemporaryDirectory(dir=root/'neptune_linux') as tmp:
    output=Path(tmp)/'neptune-bridge.exe'
    command=[compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-s',str(root/'neptune_linux/bridge/main.cpp'),'-o',str(output),'-lws2_32','-lxinput9_1_0']
    if os.environ.get('LUNA_TOOLCHAIN_BIN'):command.insert(1,'-B'+os.environ['LUNA_TOOLCHAIN_BIN'].rstrip('/')+'/')
    subprocess.run(command,check=True)
    os.replace(output,root/'neptune_linux/neptune-bridge.exe')
print('Native Proton helper built.')
