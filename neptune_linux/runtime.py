"""Linux runtime.

The helper-backed `Process` is the only platform difference. Attach reports its phases
so the (slow) Proton helper launch is visible on the status line; everything else —
discovery, ticks, restore and detach — is upstream.
"""
from neptune.core.runtime import Runtime as UpstreamRuntime, STATE_WAITING
from .process import set_progress


class Runtime(UpstreamRuntime):
    def attach(self):
        if self.attached:
            return True, self._message
        set_progress(lambda message: self._set_status(STATE_WAITING, message))
        try:
            return super().attach()
        finally:
            set_progress(None)
