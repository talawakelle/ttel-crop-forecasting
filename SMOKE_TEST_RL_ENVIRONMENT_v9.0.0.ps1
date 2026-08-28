$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v9\rl_environment_runs"
$Pointer = Join-Path $OutputRoot "LATEST_RL_ENVIRONMENT_DESIGN_RUN.txt"
if (-not (Test-Path $Pointer)) { throw "No completed RL environment design run was found." }
$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Manifest = Join-Path $RunFolder "rl_environment_manifest.json"
$EnvironmentCode = Join-Path $RunFolder "environment_code"
$TestScript = Join-Path $OutputRoot "manual_rl_environment_smoke_test.py"
@"
import sys
from pathlib import Path
sys.path.insert(0, r"$EnvironmentCode")
from tte_workforce_rl_env import TTEWorkforceRLEnvironment
env = TTEWorkforceRLEnvironment(Path(r"$Manifest"), max_moves=5)
episode = env.episode_ids()[0]
state = env.reset(episode, "SHOCK_01")
actions = env.valid_actions()
safe = [a for a in actions if a["safe_action"] == "YES"]
selected = max(safe, key=lambda a: float(a["projected_reward"]))
next_state, reward, terminated, info = env.step(selected["action_id"])
print({"episode": episode, "initial_state": state, "available_actions": len(actions), "safe_actions": len(safe), "selected_action": selected["action_id"], "reward": reward, "accepted": info["accepted"], "next_state": next_state, "rl_started": False})
"@ | Set-Content -Path $TestScript -Encoding UTF8
if (Get-Command py -ErrorAction SilentlyContinue) { py $TestScript } else { python $TestScript }
