"""Render upstream pages natively without connecting to the game."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('XDG_DATA_HOME','/tmp/neptune-ui-review')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme,setTheme,setThemeColor
from neptune.app import build_registry
from neptune.core.settings import Settings
from neptune_linux.runtime import Runtime
from neptune_linux.shell import Shell
from neptune.ui import theme as T
app=QApplication([]);app.setStyle('Fusion');app.setFont(T.ui_font())
setTheme(Theme.DARK);setThemeColor(T.ACCENT);app.setStyleSheet(T.stylesheet())
settings=Settings();settings.set('check_for_updates',False)
# This renders pages only; never auto-attach to a running game.
settings.set('auto_attach',False)
# UI verification does not need to open an audio device (headless CI has none).
import neptune.core.paths as paths
_original_asset=paths.asset
paths.asset=lambda name: None if name.startswith('sfx/') else _original_asset(name)
registry=build_registry(settings);runtime=Runtime(registry)
window=Shell(registry,runtime,settings)
output=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/neptune-native-ui');output.mkdir(parents=True,exist_ok=True)
errors=[]
def ready():
    window.show()
    pages=list(window._pages)+list(window._overlay_pages)
    def capture():
        if not pages:
            window.close();app.quit();return
        name=pages.pop(0)
        if name in window._overlay_pages:window._open_overlay(name)
        else:window.show_page(name)
        def save():
            if not window.grab().save(str(output/(name+'.png'))):errors.append(name)
            QTimer.singleShot(20,capture)
        QTimer.singleShot(100,save)
    QTimer.singleShot(150,capture)
window.ready.connect(ready)
QTimer.singleShot(20000,lambda:(errors.append('timeout'),app.quit()))
app.exec()
assert not errors,errors
print('Rendered pages:',', '.join(p.stem for p in output.glob('*.png')))
