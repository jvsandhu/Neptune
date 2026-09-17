import struct,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from neptune.memory.process import Process,ProcessError
from neptune_linux import input as inp,process

class Bridge:
    def __init__(self):self.data={};self.closed=False;self.reply='1 '+bytes(32).hex()+' 1,4096,0,255 0,0,0,0 0,0,0,0 0,0,0,0'
    def read(self,address,size):return bytes(self.data.get(address+i,0) for i in range(size))
    def write(self,address,data):self.data.update({address+i:v for i,v in enumerate(data)})
    def close(self):self.closed=True
    def call(self,op):
        if op=='ALIVE':return '1'
        if op=='NEPTUNE_INPUT':return self.reply
        if op=='MAPS':return '10000 4096 4 131072\n20000 8192 2 131072'
        raise AssertionError(op)

class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.p=Process(1,1,0x140000000,'forzahorizon6.exe');self.p.bridge=Bridge()
        self.p._alive=True
    def tearDown(self):process.active_process=None;inp._owner=None;inp._last=0
    def test_typed_access_and_chain(self):
        self.p.bridge.write(0x100,struct.pack('<2f',1.1,2.2))
        self.assertAlmostEqual(self.p.f32_array(0x100,2)[0],1.1,places=6)
        self.p.bridge.write(self.p.base+8,struct.pack('<Q',0x500))
        self.assertEqual(self.p.chain(8,16),0x510)
    def test_write_reaches_the_bridge(self):
        self.assertTrue(self.p.set_f32(0x100,1.1))
        self.assertAlmostEqual(self.p.f32(0x100),1.1,places=6)

    def test_regions_and_close(self):
        self.assertEqual(self.p.writable_regions(),[(0x10000,4096)])
        self.assertTrue(self.p.alive);process.active_process=self.p
        self.p.close();self.assertFalse(self.p.alive);self.assertIsNone(process.active_process)
    def test_controller_and_disconnect_clear_input(self):
        process.active_process=self.p
        self.assertTrue(inp.controller_connected());self.assertTrue(inp.pad_down(4096));self.assertTrue(inp.pad_down(0x20000))
        self.assertFalse(inp.pad_down(0x10000))
        process.active_process=None
        self.assertFalse(inp.pad_down(4096))
    def test_protected_operations_do_not_silently_write(self):
        with self.assertRaises(ProcessError):self.p.write_suspended(0x100,b'bad')
        self.assertEqual(self.p.bridge.data,{})

    def test_alive_is_cached_and_never_calls_the_bridge(self):
        # The GUI thread reads liveness every refresh; it must not perform IPC there.
        calls=[]
        self.p.bridge.call=lambda op,*a:(calls.append(op),'1')[1]
        self.assertTrue(self.p.alive)
        self.assertEqual(calls,[])
        self.p._alive=False
        self.assertFalse(self.p.alive)
    def test_feature_imports_remain_shared(self):
        import neptune.features.engine,neptune.features.turbo
        self.assertEqual(neptune.features.engine.EngineModule.__module__,'neptune.features.engine')

if __name__=='__main__':unittest.main()

class WheelTests(unittest.TestCase):
    def test_buttons_and_hat_only_ignore_steering_axes(self):
        from neptune_linux.wheels import Device,apply_event
        d=Device(0,1,2,'Test wheel',axis_map=[0,16,17])
        apply_event(d,1,0x81,3)
        self.assertEqual(d.button_bits,8)
        apply_event(d,0,1,3);self.assertEqual(d.button_bits,0)
        apply_event(d,32000,2,0);self.assertEqual(d.axes,{})
        apply_event(d,-32767,2,1);self.assertEqual(d.axes,{16:-32767})


class LifecycleTests(unittest.TestCase):
    def _runtime(self):
        from neptune_linux.runtime import Runtime
        class Registry:
            def __init__(self):self.events=[]
            def dispatch(self,event,*args):self.events.append(event)
        registry=Registry();runtime=Runtime(registry)
        p=Process(1,1,0x140000000,'forzahorizon6.exe');p.bridge=Bridge();p._alive=True
        runtime.process=p;runtime.vehicle=object()
        return registry,runtime,p

    def test_disconnect_restores_then_detaches(self):
        registry,runtime,p=self._runtime()
        runtime.detach()
        self.assertEqual(registry.events,['restore','on_detach'])
        self.assertTrue(p.bridge.closed)

    def test_restore_all_dispatches_restore_and_reset(self):
        registry,runtime,p=self._runtime()
        runtime.restore_all()
        self.assertEqual(registry.events,['restore','reset_controls'])


class PrewarmTests(unittest.TestCase):
    def setUp(self):
        from neptune_linux import prewarm
        self.prewarm=prewarm
        self._saved=(prewarm._bridge,prewarm._thread,prewarm._started)
        prewarm._bridge=None;prewarm._thread=None;prewarm._started=True

    def tearDown(self):
        self.prewarm._bridge,self.prewarm._thread,self.prewarm._started=self._saved

    def test_acquire_is_none_when_nothing_was_warmed(self):
        self.assertIsNone(self.prewarm.acquire())

    def test_game_running_detects_the_wine_process(self):
        import os,tempfile
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root,'123'))
            comm=os.path.join(root,'123','comm')
            with open(comm,'wb') as handle:handle.write(b'forzahorizon6.e\n')
            self.assertTrue(self.prewarm._game_running(root))
            self.assertTrue(self.prewarm._game_running(root,exe_name='ForzaHorizon6.exe'))
            with open(comm,'wb') as handle:handle.write(b'bash\n')
            self.assertFalse(self.prewarm._game_running(root))

    def test_game_is_running_delegates_to_the_host_check(self):
        from neptune_linux import process as linux_process
        original=self.prewarm._game_running
        seen=[]
        self.prewarm._game_running=lambda exe_name=None:seen.append(exe_name) or True
        try:
            self.assertTrue(linux_process.game_is_running('forzahorizon6.exe'))
            self.assertEqual(seen,['forzahorizon6.exe'])
        finally:
            self.prewarm._game_running=original

    def test_start_is_skipped_when_the_game_is_not_running(self):
        original=self.prewarm._game_running
        self.prewarm._game_running=lambda *a,**k:False
        try:
            self.prewarm._started=False;self.prewarm._thread=None
            self.prewarm.start()
            self.assertIsNone(self.prewarm._thread)
            self.assertFalse(self.prewarm._started)
        finally:
            self.prewarm._game_running=original

    def test_acquire_hands_the_bridge_over_once(self):
        class FakeBridge:
            closed=False
        bridge=FakeBridge()
        self.prewarm._bridge=bridge
        self.assertIs(self.prewarm.acquire(),bridge)
        self.assertIsNone(self.prewarm._bridge)

    def test_return_bridge_keeps_the_helper_warm_for_a_retry(self):
        class FakeBridge:
            closed=False
            def abort(self):pass
        bridge=FakeBridge()
        self.prewarm.return_bridge(bridge)
        self.assertIs(self.prewarm._bridge,bridge)
        self.assertIs(self.prewarm.acquire(),bridge)

    def test_close_aborts_an_unconsumed_bridge_without_ipc(self):
        class FakeBridge:
            closed=False
            def __init__(self):self.aborted=False
            def abort(self):self.aborted=True
        bridge=FakeBridge()
        self.prewarm._bridge=bridge
        self.prewarm.close()
        self.assertTrue(bridge.aborted)
        self.assertIsNone(self.prewarm._bridge)


class AutoAttachTests(unittest.TestCase):
    def test_auto_attach_triggers_when_the_game_is_running(self):
        from unittest.mock import patch
        from neptune.ui.shell import Shell
        class Fake:
            def __init__(self):self.called=False
            def _toggle_attach(self):self.called=True
        fake=Fake()
        with patch('neptune.memory.process.game_is_running',return_value=True):
            Shell._auto_attach(fake)
        self.assertTrue(fake.called)

    def test_auto_attach_does_nothing_without_the_game(self):
        from unittest.mock import patch
        from neptune.ui.shell import Shell
        class Fake:
            def __init__(self):self.called=False
            def _toggle_attach(self):self.called=True
        fake=Fake()
        with patch('neptune.memory.process.game_is_running',return_value=False):
            Shell._auto_attach(fake)
        self.assertFalse(fake.called)


class MultiplierCarryTests(unittest.TestCase):
    """Engine torque and Turbo multipliers carry to the new car's own stock."""

    def test_engine_keeps_torque_multiplier_and_recaptures_curve(self):
        from neptune.features.engine import EngineModule
        class Vehicle:
            rev_ceiling=7500.0
            redline=7300.0
            idle_rpm=900.0
            def curve(self):return [1.0,2.0,3.0]
        module=EngineModule(None)
        module._torque_multiplier=1.2
        module._custom_curve=[9.0,9.0]
        module._rev_limit=7000.0
        module.on_car_changed(Vehicle())
        self.assertEqual(module._torque_multiplier,1.2)
        self.assertIsNone(module._custom_curve)
        self.assertIsNone(module._rev_limit)
        self.assertEqual(module.stock_curve,[1.0,2.0,3.0])

    def test_turbo_keeps_multipliers_and_takes_the_new_stock(self):
        from neptune.features.turbo import TurboModule
        class Settings:
            def get(self,*args,**kwargs):return None
            def __getattr__(self,name):return lambda *args,**kwargs:None
        class Vehicle:
            def turbo_block(self):
                return {"max_boost":12.0,"max_scale":1.0,"low_airflow":1.0,"turbine_limit":1.0}
        module=TurboModule(Settings())
        module._multipliers["max_boost"]=1.2
        module.stock={"max_boost":10.0};module._stock_valid=True
        module.on_car_changed(Vehicle())
        self.assertEqual(module._multipliers["max_boost"],1.2)
        self.assertEqual(module.stock["max_boost"],12.0)
        self.assertTrue(module._stock_valid)

    def test_suspension_offsets_still_reset(self):
        from neptune.features.suspension import SuspensionModule
        class Settings:
            def get(self,*args,**kwargs):return None
            def __getattr__(self,name):return lambda *args,**kwargs:None
        module=SuspensionModule(Settings())
        module._lowered=True;module._front_percent=5.0;module._rear_percent=5.0
        module._capture_stock=lambda vehicle:None
        module._capture_camber_stock=lambda vehicle:None
        module._capture_track_stock=lambda vehicle:None
        module._capture_toe_stock=lambda vehicle:None
        module._capture_grip_stock=lambda vehicle:None
        module._check_rear_axle=lambda vehicle:None
        module.on_car_changed(object())
        self.assertFalse(module._lowered)
        self.assertEqual(module._front_percent,0.0)
        self.assertEqual(module._rear_percent,0.0)


class FrictionReadoutTests(unittest.TestCase):
    def test_refresh_shows_per_wheel_friction(self):
        from neptune.features.suspension import SuspensionModule
        class Settings:
            def get(self,*args,**kwargs):return None
            def __getattr__(self,name):return lambda *args,**kwargs:None
        class Vehicle:
            def wheel_read(self,field):return [0.11,0.22,0.33,0.44]
        class Recorder:
            def __init__(self):self.calls={}
            def set(self,key,value,colour=None,unit=None):self.calls[key]=value
            def reset(self):self.calls.clear()
        module=SuspensionModule(Settings())
        friction=Recorder()
        module._widgets={"stats":Recorder(),"friction":friction}
        module.refresh(Vehicle())
        self.assertEqual(friction.calls.get("friction_fl"),"0.11")
        self.assertEqual(friction.calls.get("friction_rl"),"0.44")


class GripSliderTests(unittest.TestCase):
    """Two sliders scale the per-wheel grip fields; the compound's own values are kept."""

    def _fake(self):
        from neptune.features.suspension import SuspensionModule
        from neptune.memory import offsets as O
        class Process:
            def __init__(self):self.mem={}
            def f32(self,address):return self.mem.get(address)
            def set_f32(self,address,value):self.mem[address]=value;return True
        class Vehicle:
            def __init__(self):self.process=Process();self.car=0
        class Settings:
            def get(self,*args,**kwargs):return None
            def __getattr__(self,name):return lambda *args,**kwargs:None
        module=SuspensionModule(Settings())
        vehicle=Vehicle()
        for i in range(O.Wheels.COUNT):
            vehicle.process.mem[O.Wheels.BASE+i*O.Wheels.STRIDE+0x0374]=0.985
            vehicle.process.mem[O.Wheels.BASE+i*O.Wheels.STRIDE+0x0378]=0.985
        return module,vehicle

    def test_sliders_scale_their_own_field(self):
        from neptune.memory import offsets as O
        module,vehicle=self._fake()
        module.vehicle=vehicle
        module._capture_grip_stock(vehicle)
        module._set_grip_lateral(2.0)
        base=O.Wheels.BASE
        self.assertAlmostEqual(vehicle.process.mem[base+0x0374],1.97)
        self.assertAlmostEqual(vehicle.process.mem[base+0x0378],0.985)   # untouched
        module._set_grip_longitudinal(1.5)
        self.assertAlmostEqual(vehicle.process.mem[base+0x0378],1.4775)

    def test_reset_restores_stock(self):
        from neptune.memory import offsets as O
        module,vehicle=self._fake()
        module.vehicle=vehicle
        module._capture_grip_stock(vehicle)
        module._set_grip_lateral(2.0)
        module._set_grip_longitudinal(2.0)
        module._reset_grip()
        self.assertAlmostEqual(vehicle.process.mem[O.Wheels.BASE+0x0374],0.985)
        self.assertAlmostEqual(vehicle.process.mem[O.Wheels.BASE+0x0378],0.985)

    def test_both_slider_sets_both_fields(self):
        from neptune.memory import offsets as O
        module,vehicle=self._fake()
        module.vehicle=vehicle
        module._capture_grip_stock(vehicle)
        module._set_grip_both(1.5)
        base=O.Wheels.BASE
        self.assertAlmostEqual(vehicle.process.mem[base+0x0374],0.985*1.5)
        self.assertAlmostEqual(vehicle.process.mem[base+0x0378],0.985*1.5)
        self.assertEqual(module._grip_lateral,1.5)
        self.assertEqual(module._grip_longitudinal,1.5)

    def test_reapply_never_compounds(self):
        from neptune.memory import offsets as O
        module,vehicle=self._fake()
        module.vehicle=vehicle
        module._capture_grip_stock(vehicle)
        module._set_grip_lateral(2.0)
        base=O.Wheels.BASE
        stock=module._grip_stock[0][0]
        vehicle.process.mem[base+0x0374]=stock*1.4   # physics nudges the live value
        module._last_grip_reapply=0.0
        module._reapply_grip_if_rebaked(vehicle)
        self.assertEqual(module._grip_stock[0][0],stock)              # base unchanged
        self.assertAlmostEqual(vehicle.process.mem[base+0x0374],stock*2.0)


class CarNameLabelTests(unittest.TestCase):
    def test_update_car_name(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from neptune.ui.shell import Shell
        class FakeLabel:
            def __init__(self):self._t=""
            def text(self):return self._t
            def setText(self,text):self._t=text
        class Vehicle:
            media_name="BMW_E36M3_97"
            car_config=0x1000
            class process:
                @staticmethod
                def i32(address):return 1234
        shell=SimpleNamespace(car_name=FakeLabel(),_set_text=Shell._set_text)
        with patch("neptune.ui.shell.carnames.label",return_value="BMW M3 1997"):
            Shell._update_car_name(shell,Vehicle())
        self.assertEqual(shell.car_name.text(),"BMW M3 1997")
        Shell._update_car_name(shell,None)
        self.assertEqual(shell.car_name.text(),"No car loaded")
