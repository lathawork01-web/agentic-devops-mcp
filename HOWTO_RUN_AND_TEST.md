# HOW TO RUN — agentic-devops-mcp

Step-by-step: verify the safety mechanism first (no API key needed), then run the full agent with the human-approval flow across all three risky-action types.

---

## Prerequisites

| Tool | Check installed | Install if missing |
|---|---|---|
| Python ≥ 3.10 | `python3 --version` | https://www.python.org/downloads/ |
| An Anthropic API key (for the live demo only) | — | https://console.anthropic.com/ |

The core demo (Linux tools + approval mechanism) runs entirely on your local machine — no cloud account required. AWS and Kubernetes tools are optional extensions that need real credentials/cluster access to actually execute.

---

## Step 1 — Clone and install

```bash
git clone https://github.com/<your-username>/agentic-devops-mcp.git
cd agentic-devops-mcp

python3 -m venv venv
source venv/bin/activate

pip install -r mcp_server/requirements.txt
pip install -r client/requirements.txt
```

## Step 2 — Run the safety mechanism tests FIRST

Before running any live agent, prove to yourself the approval mechanism actually works:

```bash
python tests/test_approval.py
```

Expected output:
```
All approval tests passed.
```

This runs 8 tests verifying:
- Proposing an action does **not** execute it
- Confirming with the right token **does** execute it
- Tokens are single-use (a second confirm attempt is rejected)
- Invalid and expired tokens are rejected
- **Declining** an action discards it without executing, and the token becomes unusable afterward
- The **audit log** correctly records the full lifecycle of a proposal (proposed → confirmed_and_executed, with the actual result)
- The audit log correctly records rejected confirm attempts too

If you only run one thing from this whole project to show in an interview, run this — it's proof, not just a claim.

## Step 3 — Test the MCP server standalone (no LLM yet)

```bash
cd mcp_server
python server.py
```

It should start and wait silently (MCP servers communicate over stdio — no visible output is expected). Press Ctrl+C to stop it.

## Step 4 — Run the full live demo with Claude

```bash
export ANTHROPIC_API_KEY=your_key_here
cd client
python example_client.py "Check my disk usage and memory usage"
```

You should see Claude call `check_disk_usage` and `check_memory_usage` (read-only — no approval prompt) and summarize the results in plain English.

## Step 5 — Trigger the human-in-the-loop approval flow (Linux)

```bash
python example_client.py "Check if the cups service is running, and restart it if it's not active"
```
*(Swap `cups` for any systemd service you actually have if you're not on a system with cups.)*

Watch for this exact sequence:
1. Claude calls `check_service_status` — executes immediately, no prompt
2. If it decides a restart is needed, Claude calls `propose_restart_service` — returns a token, **nothing happens yet**
3. The script pauses: `⚠️ Claude wants to call: confirm_action({...}) Approve this action? [y/N]:`
4. Type `n` first — confirm the service state is unchanged (`systemctl status cups`)
5. Run it again, type `y` this time — confirm the restart actually happened

**Both outcomes matter for this test.**

## Step 6 — Test the Kubernetes scale action (optional, needs a cluster)

```bash
# Point kubectl at any cluster you have — kind, minikube, or real
kubectl create deployment nginx-test --image=nginx --replicas=2 -n default

python example_client.py "Scale nginx-test to 4 replicas"
```
Decline first (`n`), verify `kubectl get deployment nginx-test` still shows 2 replicas. Run again, approve (`y`), verify it now shows 4.

## Step 7 — Test the AWS stop-instance action (optional, needs real AWS credentials)

**Careful — this genuinely stops a real EC2 instance if you approve it.** Use a throwaway test instance, never anything you care about.

```bash
aws configure   # if not already done
python example_client.py "Stop EC2 instance i-xxxxxxxxxxxxxxxxx"
```
Decline first, verify the instance is still running via `aws ec2 describe-instances`. This step is genuinely optional — the Linux and Kubernetes steps already prove the pattern works identically across domains.

## Step 8 — Review the audit log

After running a few of the steps above:

```bash
python3 -c "
import sys; sys.path.insert(0, 'mcp_server')
import approval
for entry in approval.read_audit_log(limit=20):
    print(entry)
"
```

You should see a chronological record of every `proposed`, `confirmed_and_executed`, `declined`, and `confirm_rejected` event from your session — this is the durable record, independent of the process having restarted.

## Step 9 — (Optional) Connect it to Claude Desktop instead of the CLI client

1. Open `claude_desktop_config.example.json`, update the absolute paths for your machine
2. Copy its contents into your Claude Desktop config:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
3. Restart Claude Desktop, then ask it: *"Check my disk usage"* — the tools appear automatically, and Claude Desktop's own tool-approval UI handles the confirmation step

---

## Testing checklist

- [ ] `python tests/test_approval.py` — all 8 tests pass
- [ ] Read-only tools execute without any approval prompt
- [ ] `propose_restart_service` returns a token but does **not** restart the service — verify with `systemctl status` before confirming
- [ ] Declining (`n`) results in the service state being unchanged, and the audit log shows a `declined` event
- [ ] Approving (`y`) results in the actual restart happening, and the audit log shows `confirmed_and_executed` with a real result string
- [ ] Attempting to reuse the same confirmation token a second time is rejected (both via the live demo and via `test_approval.py`'s dedicated test)
- [ ] The audit log file (`mcp_server/audit_log.jsonl`) persists across separate Python process runs — proposing in one run and checking the log in a fresh process should still show it

## Common issues

| Problem | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: mcp` | Dependencies not installed, or wrong venv active | Re-run the `pip install` commands from Step 1 with venv activated |
| `systemctl: command not found` | You're on macOS, not Linux | Test inside a Linux VM/container, or focus your demo on the Kubernetes/AWS actions instead |
| AWS tools fail with credentials error | No AWS credentials configured | Run `aws configure` first, or skip AWS tool testing — optional for the core demo |
| Claude never proposes the risky action | The model judged the action wasn't warranted | Try a more explicit prompt: "The service is down, please restart it" |
| Audit log file not found | No action has been proposed yet in this environment | Run Step 5 or the test suite first — the file is created on first write |

---
*Companion to the main [README.md](./README.md) — this file is the step-by-step execution guide; the README explains the design decisions.*
