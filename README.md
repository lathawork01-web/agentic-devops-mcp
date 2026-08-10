# agentic-devops-mcp

An AI agent that can investigate *and act on* infrastructure across Linux, AWS, and Kubernetes through MCP — with every state-changing action gated behind an explicit human approval step, enforced in code, not just assumed from client behavior.

## Architecture

```
                        User
                         ↓
                     AI Agent (Claude)
                         ↓
                        MCP
                         ↓
        ┌────────────────┼────────────────┐
        ↓                ↓                ↓
      Linux             AWS              K8s
        ↓                ↓                ↓
   systemctl          EC2/S3/IAM       kubectl-equivalent
   journalctl                          (pods/logs/deployments)
   disk/memory
```

## Three examples, in increasing order of risk

**1. Read-only investigation (executes immediately):**
```
User: "Check why nginx is down."
Agent: → check_service_status("nginx")
       → get_service_logs("nginx")
       → check_port(80)
       → check_disk_usage()
       → "nginx is inactive (dead). Logs show 'Address already in use' on
          port 80 — something else is bound to that port. Disk usage is
          fine, this isn't a disk space issue."
```

**2. Read-only Kubernetes investigation:**
```
User: "Show unhealthy Kubernetes pods."
Agent: → get_pods("default")  →  flags 2 pods as unhealthy
       → describe_pod() on each
       → get_pod_logs() on each
       → explains the likely cause for each
```

**3. A state-changing action — this is where it gets interesting:**
```
User: "Restart the nginx service."

Agent calls propose_restart_service("nginx")
   → returns a description + confirmation_token
   → action has NOT happened yet

Client shows the human: "Claude wants to call: confirm_action(...)
   Approve this action? [y/N]"

Only on "y" does confirm_action() actually run systemctl restart.
```

**4. Declining an action — the other half of human-in-the-loop that most demos skip:**
```
User: "Scale down payment-api to 0 replicas."

Agent calls propose_scale_deployment("payment-api", "production", 0)
   → returns a description + confirmation_token

Client shows the human the proposal. The human types "n".

decline_action(token) is called instead of confirm_action() —
the deployment is untouched, and the audit log records exactly
what was proposed and that it was declined, and why.
```

## Why the approval mechanism is implemented the way it is

Most "human-in-the-loop" AI agent demos rely entirely on the *client's* UI to ask permission before any tool call — which is reasonable, but means the safety boundary lives in the client, not the tool itself. This project puts the boundary in the **tool layer instead**:

- `propose_*` functions are completely separate from the actual state-changing logic. Calling one **cannot** change anything — it only returns a description and a single-use token.
- `confirm_action(token)` is the only function that can actually execute a change, and it requires the exact token from the proposal.
- Tokens **expire after 5 minutes** and are **single-use** — see `mcp_server/approval.py` and its accompanying tests in `tests/test_approval.py`.
- Every proposal, confirmation, decline, and rejected attempt is written to a durable **JSONL audit log** (`mcp_server/audit_log.jsonl`), independent of the process's in-memory state — so there's a record of what was proposed and what actually happened even after a restart.

This means even if a client had a bug and called tools automatically without asking, a state change still can't happen without two separate, distinct tool calls — `propose_*` then `confirm_action` with the right token. The example client (`client/example_client.py`) additionally intercepts `confirm_action` calls and requires a typed `y` in the terminal, as a second layer on top of the tool-level design.

## The three risky actions covered

| Action | Propose function | What confirming it actually does |
|---|---|---|
| Restart a Linux service | `propose_restart_service(service_name)` | `systemctl restart <service>`, then verifies the new state |
| Scale a Kubernetes Deployment | `propose_scale_deployment(name, namespace, replicas)` | Patches the Deployment's replica count via the Kubernetes API, then reads back the result to confirm it took |
| Stop an EC2 instance | `propose_stop_ec2_instance(instance_id, region)` | Calls `ec2.stop_instances`, then reports the resulting instance state |

All three follow the identical propose → human review → confirm pattern — adding a fourth risky action means adding one more `propose_*` function in `approval.py`, not rethinking the safety design.

## Repo structure

```
mcp_server/
├── server.py              # MCP server — wires up all 19 tools
├── approval.py             # The propose/confirm safety mechanism + audit log (read this first)
└── tools/
    ├── linux_tools.py       # systemctl, journalctl, disk, memory, ports — all read-only
    ├── aws_tools.py         # EC2/S3/IAM/ECR — all read-only (Describe/List/Get only)
    └── k8s_tools.py         # pods, logs, deployments — all read-only
client/
└── example_client.py       # Full demo including the terminal approval prompt
tests/
└── test_approval.py         # 8 tests covering propose/confirm/decline/expiry/audit-log
```

## Run it

```bash
cd mcp_server && pip install -r requirements.txt
cd ../client && pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here

python example_client.py "Check why nginx is down, and restart it if that's the right fix."
```

Or verify the safety mechanism alone, no API key or infrastructure needed:
```bash
python tests/test_approval.py
```

Check what the agent has actually done, at any time:
```python
import approval
for entry in approval.read_audit_log(limit=20):
    print(entry)
```

## What I'd add next

- A web UI approval flow instead of a terminal prompt, for use outside a local CLI context
- Rate limiting on proposals (e.g. max N pending proposals per session) to prevent an agent from flooding a human with approval requests
- Structured audit log querying (currently just JSONL — fine for a portfolio project, would want SQLite or similar at real scale)

## Stack

Python · Model Context Protocol (MCP) · Anthropic Claude · boto3 · Kubernetes Python client · systemd/journalctl

---
*Part of my DevOps/AI portfolio while job hunting for roles in Germany/Netherlands. More at [linkedin.com/in/latha-s-devops](https://linkedin.com/in/latha-s-devops).*
