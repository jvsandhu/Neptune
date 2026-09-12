"""Verify native overlay geometry and X Shape input handling on disposable windows."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QWidget
from Xlib.ext import shape
from neptune.ui.gamewindow import GameWindowTracker
app=QApplication([])
game=QWidget();game.setWindowTitle('Neptune overlay test surface');game.resize(600,400);game.move(80,80);game.show()
overlay=QWidget();overlay.resize(100,100);overlay.show()
errors=[]
def test():
    tracker=GameWindowTracker(int(overlay.winId()))
    try:
        tracker.game_hwnd=tracker.connection.create_resource_object('window',int(game.winId()))
        tracker._active=True
        bounds=tracker.sync()
        assert (bounds.width,bounds.height)==(600,400),(bounds.width,bounds.height)
        assert tracker.anchor(1,1,100,100)==(bounds.x+500,bounds.y+300)
        tracker.make_overlay(True);tracker.connection.sync()
        assert not tracker.window.shape_get_rectangles(shape.SK.Input).rectangles
        tracker.make_overlay(False);tracker.connection.sync()
        assert tracker.window.shape_get_rectangles(shape.SK.Input).rectangles
        print('Overlay geometry, anchor, click-through and unlock passed.')
    except Exception as error:errors.append(repr(error))
    finally:tracker.detach();overlay.close();game.close();app.quit()
QTimer.singleShot(700,test)
app.exec()
assert not errors,errors
