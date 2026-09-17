"""Linux platform shell.

Attach and teardown are the only differences from the upstream shell.

Attach: launching the Proton helper takes seconds, so it runs on a worker thread and reports
its progress on the status line.

Teardown: every write is a synchronous helper round-trip, so upstream's on-thread restore and
detach froze the window for as long as they took (the desktop marked it unresponsive). The
memory writes now run on a worker thread; `reset_controls` and the overlay lifecycle stay on
the GUI thread because they touch widgets.
"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import threading

from neptune.ui.shell import Shell as UpstreamShell


class Shell(UpstreamShell):
    def __init__(self, registry, runtime, settings):
        # The invoker must be created on the GUI thread before the runtime thread can
        # post overlay construction back to it.
        from .dispatch import ensure_invoker
        ensure_invoker()
        super().__init__(registry, runtime, settings)
        self._restoring = False
        self._closing = False
        self._close_ready = False

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

    def _restore_all(self):
        """Restore stock values without blocking the GUI thread on helper round-trips.

        `reset_controls` runs first on the GUI thread: it is cheap, it touches widgets, and
        clearing the tune state stops the runtime thread from re-applying a curve while the
        stock values are being written underneath it.
        """
        if getattr(self, '_restoring', False):
            return
        self._restoring = True
        self.registry.dispatch("reset_controls")
        state = {'done': False}

        def work():
            try:
                self.registry.dispatch("restore")
            finally:
                state['done'] = True

        threading.Thread(target=work, daemon=True, name='neptune-restore').start()

        def poll():
            if not state['done']:
                QTimer.singleShot(50, poll)
                return
            self._restoring = False
            self._sync_all_controls()

        QTimer.singleShot(50, poll)

    def closeEvent(self, event):
        if getattr(self, '_close_ready', False):
            # Second pass: the async teardown finished, so let the window go.
            self._timer.stop()
            event.accept()
            return
        if getattr(self, '_closing', False):
            event.ignore()
            return
        if getattr(self, '_attaching', False):
            # An attach is in flight. Refuse this close but schedule a retry, so a slow helper
            # launch can never leave the window unable to close.
            event.ignore()
            QTimer.singleShot(1000, self.close)
            return

        self._closing = True
        self._timer.stop()
        # Hide immediately. The teardown below talks to the helper synchronously; keeping the
        # window visible through that is what made the desktop report "not responding".
        self.hide()
        event.ignore()
        self._begin_shutdown()

    def _begin_shutdown(self) -> None:
        registry = self.registry
        runtime = self.runtime
        # GUI thread: cheap, widget-touching, and it clears the tune state so the runtime
        # thread cannot re-apply anything while the worker writes stock values back.
        registry.dispatch("reset_controls")
        state = {'done': False}

        def work():
            try:
                runtime.stop()
                registry.dispatch("restore")
                process = runtime.process
                if process is not None:
                    try:
                        process.close()
                    except Exception:
                        pass
            finally:
                state['done'] = True

        threading.Thread(target=work, daemon=True, name='neptune-shutdown').start()

        def poll():
            if not state['done']:
                QTimer.singleShot(50, poll)
                return
            runtime.vehicle = None
            runtime.process = None
            registry.dispatch("on_detach")
            registry.dispatch("shutdown")
            self._close_ready = True
            self.close()
            application = QApplication.instance()
            if application is not None:
                application.quit()

        QTimer.singleShot(50, poll)
