import importlib.util, sys, json
from pathlib import Path
W = Path("/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1")
spec = importlib.util.spec_from_file_location("cfe", W / "peos/examples/barebones/contract-file.py")
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)
mods = sorted(m for m in sys.modules if m.startswith("pmpe"))
out = {"pmpe_modules_loaded_by_contract_file_import": len(mods),
       "real_behavior_drift_eval_loaded": "pmpe.evals.real_behavior_drift_eval" in sys.modules,
       "acceptance_loaded": "pmpe.contracts.acceptance" in sys.modules,
       "barebones_cmd_loaded": "pmpe.cli.barebones_cmd" in sys.modules,
       "barebones_loaded": "pmpe.barebones" in sys.modules,
       "modules": mods}
# diagnostics of compiling the approved contract with the bound compiler
from pmpe.contracts.canonical import strict_loads
from pmpe.contracts import acceptance as acc
import inspect
out["compile_acceptance_plan_signature"] = str(inspect.signature(acc.compile_acceptance_plan))
(W / "logs" / "imports.json").write_text(json.dumps(out, indent=2))
print(json.dumps({k: v for k, v in out.items() if k != "modules"}, indent=1))
