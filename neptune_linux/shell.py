"""Linux platform shell.

Presentation and behavior are the upstream shell unchanged. The only difference is the
attach flow: launching the Proton helper can take several seconds, so it runs on a
worker thread and reports its progress on the status line.
"""
from PySide6.QtCore import QTimer
import threading
from neptune.ui.shell import Shell as UpstreamShell


class Shell(UpstreamShell):
    def __init__(self, registry, runtime, settings):
        # The invoker must be created on the GUI thread before the runtime thread can
        # post overlay construction back to it.
        from .dispatch import ensure_invoker
        ensure_invoker()
        super().__init__(registry, runtime, settings)

    def _toggle_attach(self):
        if getattr(self, '_attaching', False):
            return
        if self.runtime.attached:
            return super()._toggle_attach()
        self._attaching = True
        self.attach_icon_button.setEnabled(False)
        self.status_text.setText('Connecting to Proton…')
        from neptune.core.runtime import STATE_WAITING
        self.runtime._set_status(STATE_WAITING, 'Connecting to Proton…')
        self._attach_result = None

        def operation():
            try:
                self._attach_result = self.runtime.attach()
            except Exception as error:
                self._attach_result = (False, str(error))

        self._attach_thread = threading.Thread(target=operation, daemon=True, name='neptune-attach')
        self._attach_thread.start()

        def finish():
            if self._attach_thread.is_alive():
                QTimer.singleShot(100, finish)
                return
            self._attaching = False
            self.attach_icon_button.setEnabled(True)
            if not self._attach_result[0]:
                from neptune.core.runtime import STATE_DETACHED
                self.runtime._set_status(STATE_DETACHED, self._attach_result[1])

        QTimer.singleShot(100, finish)

    def closeEvent(self, event):
        if getattr(self, '_attaching', False):
            event.ignore()
            return
        super().closeEvent(event)
