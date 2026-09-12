"""Linux adapter helpers.

`wrap_module` keeps overlay construction on the GUI thread: `on_attach` runs on the
runtime thread and builds QWidget overlays, which is not thread-safe. `direct_read`
lets a main-thread caller bypass the display cache when it needs a value immediately.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect

from .dispatch import on_gui_thread, post_to_gui

direct_read = ContextVar('neptune_direct_read', default=False)


@contextmanager
def live_reads():
    token = direct_read.set(True)
    try:
        yield
    finally:
        direct_read.reset(token)


def wrap_module(module):
    for name in dir(module):
        if name.startswith('__'):
            continue
        method = getattr(module, name)
        if not inspect.ismethod(method):
            continue

        def wrap(method, name):
            @wraps(method)
            def call(*args, **kwargs):
                if name == '_ensure_overlay' and not on_gui_thread():
                    # Overlays build QWidgets and start QTimers; doing that off the GUI
                    # thread corrupts Qt's thread-local font engines and can SIGSEGV later.
                    post_to_gui(lambda: method(*args, **kwargs))
                    return
                return method(*args, **kwargs)

            return call

        setattr(module, name, wrap(method, name))
    return module
