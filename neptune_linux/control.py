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

# Module methods that may construct a Qt overlay. This is a naming convention, not a guarantee;
# the port's contract test asserts that every method which actually builds a widget matches it,
# so a future builder under a different name fails in CI instead of SIGSEGV-ing at runtime.
OVERLAY_BUILDER_PREFIXES = ('_ensure_', '_build_', '_create_')


def builds_overlay(name):
    """True when a module method must be marshalled onto the GUI thread."""
    return name.startswith(OVERLAY_BUILDER_PREFIXES) and 'overlay' in name


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
                if builds_overlay(name) and not on_gui_thread():
                    # Overlays build QWidgets and start QTimers; doing that off the GUI
                    # thread corrupts Qt's thread-local font engines and can SIGSEGV later.
                    post_to_gui(lambda: method(*args, **kwargs))
                    return
                return method(*args, **kwargs)

            return call

        setattr(module, name, wrap(method, name))
    return module
