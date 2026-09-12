"""Read-only verification of Neptune's vehicle and engine discovery under Proton."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neptune.memory.process import Process
from neptune.vehicle.vehicle import find_vehicles
from neptune_linux.control import live_reads
p=Process.attach('forzahorizon6.exe')
try:
    def reject(*args):raise AssertionError('Read-only validation attempted a write')
    p.write=reject;p.write_protected=reject;p.write_suspended=reject
    # This runs on the main thread, where reads go through the display cache; force live
    # reads so discovery sees real memory.
    with live_reads():
        vehicles,error=find_vehicles(p)
        report={'mode':'read_only','writes':0,'error':error,'vehicles':[]}
        for v in vehicles[:4]:
            curve=v.curve()
            report['vehicles'].append({'valid':v.is_car(),'curve_writable_checks':v.can_tune_curve(),'points':len(curve),'rpm':v.rpm,'engine_rpm':v.engine_speed_rpm,'fingerprint':v.fingerprint(),'curve_min':min(curve) if curve else None,'curve_max':max(curve) if curve else None})
    fields=p.bridge.call('NEPTUNE_INPUT').split()
    report['controllers']=[int(row.split(',')[0]) for row in fields[2:]]
    Path('linux/live-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
finally:p.close()
