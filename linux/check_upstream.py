"""Report upstream drift without modifying the checkout or merging anything."""
import argparse,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fetch',action='store_true')
parser.add_argument('--ref',default='origin/main')
args=parser.parse_args()
def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
lock=json.loads((root/'linux/upstream.json').read_text())
if args.fetch:subprocess.run(['git','fetch','origin'],cwd=root,check=True)
head=git('rev-parse',args.ref)
changed=git('diff','--name-only',lock['revision'],head).splitlines()
review=sorted(set(changed)&set(lock['watched_files']))
print(json.dumps({'tested_upstream':lock['revision'],'candidate':head,'changed_files':changed,'platform_contract_review':review,'working_tree_modified':bool(git('status','--porcelain')),'action':'No merge performed. Review changes, merge in a working branch, run Linux tests and visual/live validation before advancing the pin.'},indent=2))
