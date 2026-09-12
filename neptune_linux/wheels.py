"""Linux joystick button/hat input; no raw keyboard device access."""
import array
from dataclasses import dataclass,field
import fcntl,glob,os,struct,time
from pathlib import Path
from types import SimpleNamespace

@dataclass
class Device:
    index:int
    vendor:int
    product:int
    name:str
    buttons:int=32
    fd:int=-1
    button_bits:int=0
    axes:dict=field(default_factory=dict)
    axis_map:list=field(default_factory=list)
    def button_label(self,index):return f'Button {index+1}'

_devices=[]
_last=0.

def devices(force=False):
    global _devices,_last
    if not force and time.monotonic()-_last<2:return _devices
    _last=time.monotonic()
    old={d.index:d for d in _devices};found=[]
    for path in glob.glob('/sys/class/input/js*'):
        root=Path(path)/'device'
        try:
            index=int(Path(path).name[2:]);name=(root/'name').read_text().strip()
            if not any(word in name.lower() for word in ('wheel','g29','g920','g923','g27','g25','thrustmaster','fanatec','moza','simagic')):continue
            vendor=int((root/'id/vendor').read_text(),16);product=int((root/'id/product').read_text(),16)
            device=old.pop(index,None)
            if device and (device.vendor,device.product,device.name)!=(vendor,product,name):
                os.close(device.fd);device=None
            if device is None:
                fd=os.open('/dev/input/js'+str(index),os.O_RDONLY|os.O_NONBLOCK)
                axes=array.array('B',[0]*64)
                try:fcntl.ioctl(fd,0x80406a32,axes,True)
                except OSError:pass
                device=Device(index,vendor,product,name,fd=fd,axis_map=list(axes))
            found.append(device)
        except (OSError,ValueError):continue
    for device in old.values():
        try:os.close(device.fd)
        except OSError:pass
    _devices=found
    return found


def apply_event(device,value,kind,number):
    kind &= 0x7f
    if kind==1 and number<32:
        if value:device.button_bits |= 1<<number
        else:device.button_bits &= ~(1<<number)
    elif kind==2 and number<len(device.axis_map):
        axis=device.axis_map[number]
        if axis in (16,17):device.axes[axis]=value


def poll(index):
    device=next((d for d in devices() if d.index==index),None)
    if device is None:return None
    try:
        for _ in range(256):
            try:data=os.read(device.fd,8)
            except BlockingIOError:break
            if len(data)!=8:return None
            _,value,kind,number=struct.unpack('<IhBB',data)
            apply_event(device,value,kind,number)
    except OSError:return None
    x=device.axes.get(16,0);y=device.axes.get(17,0)
    sx=(x>10000)-(x < -10000);sy=(y>10000)-(y < -10000)
    pov={(0,-1):0,(1,-1):4500,(1,0):9000,(1,1):13500,(0,1):18000,(-1,1):22500,(-1,0):27000,(-1,-1):31500}.get((sx,sy),65535)
    return SimpleNamespace(dwButtons=device.button_bits,dwPOV=pov)
