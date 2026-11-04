"""Run the unmodified run_experiment.main with a narrow simulate subprocess adapter."""
import importlib.util,json,subprocess,sys
from pathlib import Path
from common import DEMO
sys.path.insert(0,str(DEMO))
import run_experiment

original_run=subprocess.run

def dispatch(command,*args,**kwargs):
    if isinstance(command,list) and len(command)>1 and command[1]=='simulate.py':
        command=[command[0],str(Path(__file__).with_name('simulate_runner.py'))]+command[2:]
    return original_run(command,*args,**kwargs)

run_experiment.subprocess.run=dispatch
run_experiment.main()
