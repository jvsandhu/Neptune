"""Implement upstream Process through a helper inside the selected Proton prefix."""
import contextlib
import os
import threading
import time
from .control import direct_read
from pathlib import Path
from .transport import Bridge, BridgeError

active_process = None

# Set by the Linux Runtime so attach can report its phases to the status line.
_progress = None


def set_progress(callback):
    global _progress
    _progress = callback


def _report(message):
    callback = _progress
    if callback is not None:
        try:callback(message)
        except Exception:pass


def game_is_running(exe_name='forzahorizon6.exe'):
    """True when the game is running, from the host process list.

    Auto-attach gates on this. Attach is still explicit for the helper launch; this only
    decides whether the auto-attach setting has something to attach to.
    """
    from .prewarm import _game_running
    return _game_running(exe_name=exe_name)


def adapt_process(base_class, error_class):
    class ProtonProcess(base_class):
        @classmethod
        def attach(cls, exe_name):
            global active_process
            bridge = None
            warmed = False
            try:
                from . import prewarm
                if prewarm.pending():
                    _report('Waiting for the Proton helper…')
                bridge = prewarm.acquire()
                warmed = bridge is not None
                if bridge is None:
                    _report('Launching Proton helper…')
                    bridge = Bridge.start(Path(__file__).with_name('neptune-bridge.exe'), os.environ.get('NEPTUNE_STEAM_APPID','2483190'))
                _report('Reading the game…')
                games = [line.split('\t',1) for line in bridge.call('LIST').splitlines()]
                if len(games) != 1:
                    if warmed:
                        # Nothing was attached; keep the helper warm for the retry.
                        prewarm.return_bridge(bridge)
                        bridge = None
                    raise error_class('Start one FH6 instance through Steam, then attach.')
                pid = int(games[0][0])
                response = bridge.call('ATTACH',pid).split()
                instance = cls(pid,1,int(response[0],16),exe_name)
                instance.bridge = bridge
                instance._alive=True
                instance._cache={};instance._requests={};instance._cache_lock=threading.RLock()
                instance._cache_stop=threading.Event()
                instance._cache_thread=threading.Thread(target=instance._cache_loop,daemon=True,name='neptune-display-reads')
                instance._cache_thread.start()
                active_process = instance
                return instance
            except Exception as error:
                if bridge: bridge.close()
                raise error_class(str(error)) from error

        def close(self):
            global active_process
            if active_process is self: active_process = None
            self._alive=False
            if hasattr(self,'_cache_stop'):self._cache_stop.set()
            if self.handle:
                try:self.bridge.close()
                except Exception:self.bridge.abort()
                self.handle = 0

        @property
        def alive(self):
            # Cached liveness. The GUI thread reads this every refresh; a synchronous
            # ALIVE round-trip here contended with the runtime thread on the bridge lock
            # and stalled the interface while scrolling. `_cache_loop` refreshes it.
            return bool(self.handle) and getattr(self,'_alive',False)

        @property
        def executable_path(self):
            # Asset discovery cannot use a Windows path as a Linux path.
            return os.environ.get('NEPTUNE_GAME_EXE')

        def _cache_loop(self):
            while not self._cache_stop.wait(.05):
                try:self._alive=self.bridge.call('ALIVE')=='1'
                except BridgeError:self._alive=False
                with self._cache_lock:
                    now=time.monotonic()
                    self._requests={key:t for key,t in self._requests.items() if now-t<2}
                    requests=list(self._requests)
                    self._cache={key:value for key,value in self._cache.items() if key in self._requests}
                groups={}
                for address,size in requests:
                    page=address & ~4095
                    key=(page,4096) if address+size<=page+4096 else (address,size)
                    groups.setdefault(key,[]).append((address,size))
                for (address,size),members in groups.items():
                    if self._cache_stop.is_set():return
                    try:data=self.bridge.read(address,size)
                    except BridgeError:data=None
                    with self._cache_lock:
                        for requested,count in members:
                            self._cache[(requested,count)]=data[requested-address:requested-address+count] if data is not None else None

        def read(self,address,size):
            if not address or size <= 0:return None
            if hasattr(self,'_cache') and not direct_read.get() and threading.current_thread() is threading.main_thread():
                with self._cache_lock:
                    key=(address,size);self._requests[key]=time.monotonic()
                    cached=self._cache.get(key)
                if cached is not None:
                    return cached
                # Cold key: first read of a page, or a size the cache loop has not served yet.
                # Fetch it synchronously rather than returning None, which blanked graphs and
                # stats for a frame. This runs once per key, not on every refresh, so it does
                # not put an IPC round-trip on the steady-state display path.
                try:data=self.bridge.read(address,size)
                except BridgeError:return None
                with self._cache_lock:self._cache[key]=data
                return data
            try:return self.bridge.read(address,size)
            except BridgeError:return None

        def write(self,address,data):
            if not address or not data:return False
            try:
                self.bridge.write(address,data)
                # Reflect the write into the display cache instead of clearing it. Clearing made
                # every cached read return None for a frame, which blanked the torque graph each
                # time a tune re-applied. Overlapping entries are patched in place; anything the
                # game derives from the write is refreshed by `_cache_loop` within ~50 ms.
                if hasattr(self,'_cache'):
                    end=address+len(data)
                    with self._cache_lock:
                        for key,cached in self._cache.items():
                            if cached is None:continue
                            start,size=key
                            if not (start < end and address < start+size):continue
                            lower=max(address,start);upper=min(end,start+size)
                            patched=bytearray(cached)
                            patched[lower-start:upper-start]=data[lower-address:upper-address]
                            self._cache[key]=bytes(patched)
                return True
            except Exception as error:
                raise error_class('Game write failed: '+str(error)) from error

        def write_protected(self,address,data):
            raise error_class('Protected code writes are not supported by the Linux adapter.')

        def thread_ids(self):
            return []

        @contextlib.contextmanager
        def threads_suspended(self):
            raise error_class('Thread suspension is not supported by the Linux adapter.')
            yield

        def writable_regions(self,limit=0x8000000):
            result=[]
            for row in self.bridge.call('MAPS').splitlines():
                address,size,protection,_kind=row.split()
                address=int(address,16);size=int(size);protection=int(protection)
                if address < 0x7FF000000000 and protection in (4,8,64,128):
                    result.append((address,min(size,limit)))
            return result
    return ProtonProcess
