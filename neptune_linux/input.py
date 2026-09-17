"""Keyboard and XInput bindings read through the attached Proton helper."""
import threading
import time
from . import process

_lock=threading.RLock()
_last=0.0
_owner=None
_keys=bytes(32)
_pads=[]


def _refresh():
    global _last,_owner,_keys,_pads
    owner=process.active_process
    with _lock:
        now=time.monotonic()
        if owner is _owner and now-_last < .016: return
        _last=now
        if owner is not _owner:
            # A different attachment (or none): forget the previous device's state so a key held
            # when the game closed cannot read as down against the next session.
            _owner=owner;_keys=bytes(32);_pads=[]
        if owner is None: return
        try:
            fields=owner.bridge.call('NEPTUNE_INPUT').split()
            keys=bytes.fromhex(fields[1])
            if len(fields)!=6 or len(keys)!=32: return
            pads=[tuple(map(int,row.split(','))) for row in fields[2:]]
            if any(len(row)!=4 for row in pads): return
            _keys=keys;_pads=pads
        except Exception:
            # Keep the last good sample. A dropped poll must not read as "everything released",
            # or a held binding that gates a write would drop mid-hold.
            return


def _snapshot():
    """The latest input sample, read under the lock so a refresh cannot zero it mid-read."""
    _refresh()
    with _lock:
        return _keys,_pads


def key_down(code):
    keys,_=_snapshot()
    return 0<=code<256 and bool(keys[code//8] & (1<<(code%8)))


def controller_connected():
    _,pads=_snapshot()
    return any(row[0] for row in pads)


def pad_down(code,index=0):
    _,pads=_snapshot()
    if not 0<=index<len(pads):return False
    connected,buttons,left,right=pads[index]
    if not connected:return False
    if code==0x10000:return left>=60
    if code==0x20000:return right>=60
    return bool(buttons & code)
