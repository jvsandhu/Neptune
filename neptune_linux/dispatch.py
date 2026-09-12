"""Run work on the Qt GUI thread from the runtime/attach worker threads.

Qt widgets, fonts and timers are thread-affine. Feature lifecycle callbacks such as
`on_attach` are dispatched from the runtime thread, and some of them build overlay
widgets. Constructing a QWidget (and the font engines it creates) off the GUI thread
leaves those font engines attached to the wrong thread; painting them later on the GUI
thread then dereferences a null FreeType face and the process dies with SIGSEGV.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QApplication


class _GuiInvoker(QObject):
    """A QObject that lives on the GUI thread and runs posted callables there."""

    _posted = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._posted.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, call) -> None:
        call()

    def post(self, call) -> None:
        self._posted.emit(call)


_invoker: _GuiInvoker | None = None


def ensure_invoker() -> _GuiInvoker:
    """Create the invoker. Must be called once from the GUI thread during startup."""
    global _invoker
    if _invoker is None:
        _invoker = _GuiInvoker()
    return _invoker


def gui_thread() -> QThread | None:
    application = QApplication.instance()
    return application.thread() if application is not None else None


def on_gui_thread() -> bool:
    thread = gui_thread()
    return thread is None or QThread.currentThread() is thread


def post_to_gui(call) -> None:
    """Queue `call` to run on the GUI thread's event loop."""
    ensure_invoker().post(call)
