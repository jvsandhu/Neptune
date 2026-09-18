import os,ast,struct,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
# Headless by default so the tests run in CI without a display.
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from neptune.memory.process import Process,ProcessError
from neptune_linux import input as inp,process


def ensure_qt():
    """A QApplication for the tests that build feature modules.

    Some module constructors create Qt objects (audio players, timers) for their lifetime.
    Without an application those objects outlive the interpreter and the process segfaults
    during teardown, even though every test passed. One shared application fixes that.
    """
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def setUpModule():
    ensure_qt()

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
            shift_threshold=7200.0
            neg_clamp=7400.0
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


class DisplayCacheTests(unittest.TestCase):
    """GUI-thread reads must never blank for a frame when the cache is cold or after a write.

    Regression for the torque graph blinking: `write()` cleared the whole display cache and a
    miss returned None, so every re-apply of a tune dropped the live curve for a frame.
    """

    def _process(self):
        from neptune_linux.process import adapt_process
        bridge=Bridge()
        bridge.write(0x100,struct.pack('<f',1.25))
        instance=adapt_process(Process,ProcessError)(1,1,0x140000000,'forzahorizon6.exe')
        instance.bridge=bridge
        instance._alive=True
        instance._cache={}
        instance._requests={}
        instance._cache_lock=threading.RLock()
        instance._cache_stop=threading.Event()
        self.addCleanup(instance._cache_stop.set)
        return instance

    def test_cold_read_returns_data_not_none(self):
        p=self._process()
        self.assertIsNotNone(p.f32(0x100))
        self.assertAlmostEqual(p.f32(0x100),1.25,places=6)

    def test_write_does_not_blank_following_reads(self):
        p=self._process()
        self.assertAlmostEqual(p.f32(0x100),1.25,places=6)
        self.assertTrue(p.set_f32(0x100,2.5))
        self.assertIsNotNone(p.f32(0x100))
        self.assertAlmostEqual(p.f32(0x100),2.5,places=6)

    def test_cache_loop_survives_an_unexpected_bridge_error(self):
        # A malformed frame raises ValueError (not BridgeError). The loop must keep running and
        # report the process dead, rather than dying and leaving the display stale-but-"alive".
        p=self._process()
        thread=threading.Thread(target=p._cache_loop,daemon=True)
        thread.start()
        self.addCleanup(p._cache_stop.set)
        time.sleep(0.08)
        self.assertTrue(thread.is_alive())
        p.bridge.call=lambda *a:(_ for _ in ()).throw(ValueError('malformed frame'))
        time.sleep(0.12)
        self.assertTrue(thread.is_alive(),'the cache loop must not die on an unexpected error')
        self.assertFalse(p._alive,'an unexpected bridge failure must report the process dead')


class InputDropoutTests(unittest.TestCase):
    """A dropped input poll must not read as 'everything released'."""

    X = 0x58

    def setUp(self):
        from neptune_linux import input as linux_input
        self.input=linux_input
        self._saved=(linux_input._owner,linux_input._keys,linux_input._pads,linux_input._last)
        linux_input._owner=None;linux_input._keys=bytes(32)
        linux_input._pads=[];linux_input._last=0.0
        process.active_process=None

    def tearDown(self):
        self.input._owner,self.input._keys,self.input._pads,self.input._last=self._saved
        process.active_process=None

    def _owner(self,bridge):
        owner=SimpleNamespace(bridge=bridge)
        return owner

    def test_failed_poll_keeps_the_last_sample(self):
        keys=bytearray(32);keys[self.X//8]|=1<<(self.X%8)
        class Bridge:
            fail=False
            reply='1 '+keys.hex()+' 1,4096,0,0 0,0,0,0 0,0,0,0 0,0,0,0'
            def call(self,op):
                if self.fail:raise RuntimeError('helper gone')
                return self.reply
        bridge=Bridge()
        process.active_process=self._owner(bridge)
        self.assertTrue(self.input.key_down(self.X))
        bridge.fail=True
        self.input._last=0.0  # defeat the throttle without changing the owner
        self.assertTrue(self.input.key_down(self.X),'a failed poll must keep the last good sample')

    def test_owner_change_clears_the_previous_session(self):
        keys=bytearray(32);keys[self.X//8]|=1<<(self.X%8)
        class Bridge:
            reply='1 '+keys.hex()+' 0,0,0,0 0,0,0,0 0,0,0,0 0,0,0,0'
            def call(self,op):return self.reply
        process.active_process=self._owner(Bridge())
        self.assertTrue(self.input.key_down(self.X))
        process.active_process=None
        self.assertFalse(self.input.key_down(self.X),'a key held at disconnect must not stay down')


class PortContractTests(unittest.TestCase):
    """Fail in CI when an upstream interface moves out from under the port.

    The port attaches to upstream by replacing symbols at import time and by subclassing.
    If upstream renames or removes one of those symbols the seam silently stops applying,
    so these checks turn that into a test failure instead of a runtime surprise.
    """

    REQUIRED_PROCESS_METHODS=(
        'attach','close','alive','executable_path','read','write','write_protected',
        'writable_regions','thread_ids','threads_suspended','write_suspended',
        'f32','i32','u32','pointer','f32_array','set_f32','set_i32','set_f32_array','chain',
    )

    def test_import_time_seams_still_apply(self):
        import neptune.core.input as core_input
        import neptune.core.wheels as core_wheels
        import neptune.memory.process as memory_process
        import neptune.ui.gamewindow as ui_gamewindow
        from neptune_linux import input as linux_input
        from neptune_linux import process as linux_process
        from neptune_linux import wheels as linux_wheels
        self.assertEqual(memory_process.Process.__module__,'neptune_linux.process',
                         'the memory.process Process seam stopped applying')
        self.assertIs(memory_process.game_is_running,linux_process.game_is_running,
                      'the memory.process game_is_running seam stopped applying')
        self.assertIs(core_input.key_down,linux_input.key_down,
                      'the core.input key_down seam stopped applying')
        self.assertIs(core_input.pad_down,linux_input.pad_down,
                      'the core.input pad_down seam stopped applying')
        self.assertIs(core_input.controller_connected,linux_input.controller_connected,
                      'the core.input controller_connected seam stopped applying')
        self.assertIs(core_wheels.devices,linux_wheels.devices,
                      'the core.wheels devices seam stopped applying')
        self.assertIs(core_wheels._poll,linux_wheels.poll,
                      'the core.wheels poll seam stopped applying')
        self.assertEqual(ui_gamewindow.GameWindowTracker.__module__,'neptune_linux.gamewindow',
                         'the ui.gamewindow tracker seam stopped applying')

    def test_lifecycle_subclasses_still_match_upstream(self):
        from neptune.core.runtime import Runtime as UpstreamRuntime
        from neptune.ui.shell import Shell as UpstreamShell
        from neptune_linux.runtime import Runtime as LinuxRuntime
        from neptune_linux.shell import Shell as LinuxShell
        self.assertTrue(issubclass(LinuxRuntime,UpstreamRuntime))
        self.assertTrue(issubclass(LinuxShell,UpstreamShell))

    def test_process_surface_still_covers_what_features_use(self):
        from neptune.memory.process import Process
        for name in self.REQUIRED_PROCESS_METHODS:
            self.assertTrue(hasattr(Process,name),
                            f'Process.{name} is gone; the Linux adapter needs updating')

    def test_every_overlay_builder_is_marshalled_to_the_gui_thread(self):
        from neptune_linux.control import builds_overlay
        self.assertTrue(builds_overlay('_ensure_overlay'))
        self.assertTrue(builds_overlay('_ensure_dyno_overlay'))
        self.assertTrue(builds_overlay('_build_gauge_overlay'))
        self.assertFalse(builds_overlay('tick'))
        self.assertFalse(builds_overlay('_set_overlay_mode'))
        features=Path(__file__).resolve().parents[2]/'neptune'/'features'
        gui_only={'tick','tick_process','refresh','build_page'}
        offenders=[]
        for path in sorted(features.glob('*.py')):
            tree=ast.parse(path.read_text(),filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node,ast.ClassDef):continue
                for item in node.body:
                    if not isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
                    if item.name in gui_only or builds_overlay(item.name):continue
                    if self._constructs_overlay(item):
                        offenders.append(f'{path.name}:{node.name}.{item.name}')
        self.assertEqual(offenders,[],'overlay builders not marshalled to the GUI thread: '+', '.join(offenders))

    @staticmethod
    def _constructs_overlay(function):
        for node in ast.walk(function):
            if not isinstance(node,ast.Call):continue
            target=node.func
            name=target.id if isinstance(target,ast.Name) else getattr(target,'attr','')
            if name.endswith('Overlay'):
                return True
        return False


class AsyncTeardownTests(unittest.TestCase):
    """Restore and close must not run helper round-trips on the GUI thread.

    Every write is a synchronous helper call, so upstream's on-thread restore/detach froze the
    window (the desktop reported "not responding") during Restore everything and on close.
    """

    def _patch_timer(self):
        """Replace QTimer.singleShot with a recorder so the tests need no event loop."""
        from unittest.mock import patch
        import neptune_linux.shell as linux_shell
        calls=[]
        class FakeTimer:
            @staticmethod
            def singleShot(ms,callback):calls.append((ms,callback))
        patcher=patch.object(linux_shell,'QTimer',FakeTimer)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_restore_all_dispatches_restore_off_the_caller_thread(self):
        self._patch_timer()
        from neptune_linux.shell import Shell
        main=threading.current_thread().name
        seen=[];done=threading.Event()
        class Registry:
            def dispatch(self,event,*a):
                seen.append((event,threading.current_thread().name))
                if event=='restore':done.set()
        fake=SimpleNamespace(registry=Registry(),_restoring=False,_sync_all_controls=lambda:None)
        Shell._restore_all(fake)
        self.assertIn(('reset_controls',main),seen,'reset_controls must stay on the GUI thread')
        self.assertTrue(done.wait(2.0),'the restore dispatch never ran')
        self.assertIn(('restore','neptune-restore'),seen,'restore must run off the GUI thread')

    def test_begin_shutdown_runs_the_teardown_off_the_caller_thread(self):
        self._patch_timer()
        from neptune_linux.shell import Shell
        main=threading.current_thread().name
        seen=[];done=threading.Event()
        class Registry:
            def dispatch(self,event,*a):
                seen.append((event,threading.current_thread().name))
                if event=='restore':done.set()
        class Process:
            def close(self):seen.append(('process.close',threading.current_thread().name))
        class Runtime:
            def __init__(self):self.process=Process();self.vehicle=object()
            def stop(self):seen.append(('stop',threading.current_thread().name));return True
        fake=SimpleNamespace(registry=Registry(),runtime=Runtime(),_close_ready=False,close=lambda:None)
        Shell._begin_shutdown(fake)
        self.assertIn(('reset_controls',main),seen)
        self.assertTrue(done.wait(2.0))
        self.assertIn(('stop','neptune-shutdown'),seen)
        self.assertIn(('process.close','neptune-shutdown'),seen)

    def test_close_hides_and_returns_without_blocking(self):
        self._patch_timer()
        from neptune_linux.shell import Shell
        main=threading.current_thread().name
        seen=[]
        class Event:
            def __init__(self):self.accepted=False;self.ignored=False
            def accept(self):self.accepted=True
            def ignore(self):self.ignored=True
        fake=SimpleNamespace(_close_ready=False,_closing=False,_attaching=False,
                             _timer=SimpleNamespace(stop=lambda:None),
                             hide=lambda:seen.append(('hide',main)),
                             _begin_shutdown=lambda:seen.append(('begin_shutdown',main)),
                             close=lambda:None)
        event=Event()
        started=time.monotonic()
        Shell.closeEvent(fake,event)
        self.assertLess(time.monotonic()-started,0.5,'closeEvent must not block the GUI thread')
        self.assertTrue(event.ignored)
        self.assertFalse(event.accepted)
        self.assertIn(('hide',main),seen)
        self.assertIn(('begin_shutdown',main),seen)

    def test_close_while_attaching_is_deferred_not_dropped(self):
        calls=self._patch_timer()
        from neptune_linux.shell import Shell
        class Event:
            def __init__(self):self.accepted=False;self.ignored=False
            def accept(self):self.accepted=True
            def ignore(self):self.ignored=True
        fake=SimpleNamespace(_close_ready=False,_closing=False,_attaching=True,
                             _timer=SimpleNamespace(stop=lambda:None),hide=lambda:None,
                             _begin_shutdown=lambda:None,close=lambda:None)
        event=Event()
        Shell.closeEvent(fake,event)
        self.assertTrue(event.ignored)
        self.assertTrue(any(ms==1000 for ms,_ in calls),'the close must be retried, not dropped')


class GameWindowChoiceTests(unittest.TestCase):
    """The game window is matched by PID first; the title is only a fallback."""

    def test_pid_match_wins(self):
        from neptune_linux.gamewindow import choose_game_window
        rows=[(1,'Forza Horizon 6',None,100),(2,'Something else',1234,50),(3,'Forza Horizon 6',None,900)]
        self.assertEqual(choose_game_window(rows,1234),2)

    def test_largest_titled_window_when_there_is_no_pid(self):
        from neptune_linux.gamewindow import choose_game_window
        rows=[(1,'Forza Horizon 6',None,100),(2,'Forza Horizon 6',None,900),(3,'Firefox',None,5000)]
        self.assertEqual(choose_game_window(rows,None),2)

    def test_no_match_returns_none(self):
        from neptune_linux.gamewindow import choose_game_window
        self.assertIsNone(choose_game_window([(1,'Firefox',None,5000)],None))


class HelloProtocolTests(unittest.TestCase):
    """The helper greeting carries a protocol number so a stale binary fails at connect."""

    def test_current_greeting_carries_the_protocol(self):
        from neptune_linux.transport import PROTOCOL,parse_hello
        self.assertEqual(parse_hello(f'LUNA1 {PROTOCOL} abc123'),('abc123',PROTOCOL))

    def test_pre_version_greeting_is_accepted_as_protocol_1(self):
        from neptune_linux.transport import parse_hello
        self.assertEqual(parse_hello('LUNA1 abc123'),('abc123',1))

    def test_foreign_or_malformed_greeting_is_ignored(self):
        from neptune_linux.transport import parse_hello
        self.assertEqual(parse_hello('HELLO abc123'),(None,None))
        self.assertEqual(parse_hello('LUNA1'),(None,None))
        self.assertEqual(parse_hello('LUNA1 xyz abc'),(None,None))


class RevLimitTests(unittest.TestCase):
    """The limiter is three engine-model fields, not one.

    The feature only ever wrote MAX_CLAMP (the curve's sampling bound), so a car with the
    slider maxed still cut at its stock rpm. Confirmed live: raising THRESH alone moved the
    cut to NEG_CLAMP, and raising all three let the engine reach the selected value.
    """

    def _module(self):
        from neptune.features.engine import EngineModule
        class Settings:
            def get(self,*args,**kwargs):return None
            def __getattr__(self,name):return lambda *args,**kwargs:None
        return EngineModule(Settings())

    def _recorder(self):
        calls={}
        class Vehicle:
            def set_rev_ceiling(self,rpm):calls['max_clamp']=rpm;return True
            def set_shift_threshold(self,rpm):calls['thresh']=rpm;return True
            def set_neg_clamp(self,rpm):calls['neg_clamp']=rpm;return True
        return Vehicle(),calls

    def test_setting_a_limit_writes_all_three(self):
        module=self._module()
        vehicle,calls=self._recorder()
        module._write_rev_limits(vehicle,9000.0)
        self.assertEqual(calls,{'max_clamp':9000.0,'thresh':9000.0,'neg_clamp':9000.0})

    def test_clearing_the_limit_restores_all_three(self):
        module=self._module()
        module.stock_ceiling=8000.0
        module.stock_thresh=7000.0
        module.stock_neg_clamp=7500.0
        vehicle,calls=self._recorder()
        module._write_rev_limits(vehicle,None)
        self.assertEqual(calls,{'max_clamp':8000.0,'thresh':7000.0,'neg_clamp':7500.0})

    def test_stock_capture_records_thresh_and_neg_clamp(self):
        module=self._module()
        class Vehicle:
            rev_ceiling=8000.0
            redline=7000.0
            shift_threshold=7000.0
            neg_clamp=7500.0
            def curve(self):return [1.0,2.0]
            idle_rpm=800.0
        module.on_attach(Vehicle())
        self.assertEqual(module.stock_thresh,7000.0)
        self.assertEqual(module.stock_neg_clamp,7500.0)





