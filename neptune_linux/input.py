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
        _owner=owner;_last=now;_keys=bytes(32);_pads=[]
        if owner is None: return
        try:
            fields=owner.bridge.call('NEPTUNE_INPUT').split()
            keys=bytes.fromhex(fields[1])
            if len(fields)!=6 or len(keys)!=32: return
            pads=[tuple(map(int,row.split(','))) for row in fields[2:]]
            if any(len(row)!=4 for row in pads): return
            _keys=keys;_pads=pads
        except Exception:
            return


def key_down(code):
    _refresh()
    return 0<=code<256 and bool(_keys[code//8] & (1<<(code%8)))


def controller_connected():
    _refresh()
    return any(row[0] for row in _pads)


def pad_down(code,index=0):
    _refresh()
    if not 0<=index<len(_pads):return False
    connected,buttons,left,right=_pads[index]
    if not connected:return False
    if code==0x10000:return left>=60
    if code==0x20000:return right>=60
    return bool(buttons & code)
