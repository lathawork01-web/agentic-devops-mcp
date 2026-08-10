"""
approval.py — the propose/confirm pattern for any action that changes
infrastructure state.

This is the most important file in this project. The design principle:

    Read-only diagnostics execute immediately.
    Anything that CHANGES state requires two separate, explicit steps:
        1. propose_action(...)  -> returns a description + a confirmation token
        2. confirm_action(token) -> only THEN does the actual change happen

An LLM client calling propose_action can describe what it's about to do
and show that to the user. The action does not happen until a SEPARATE
call to confirm_action is made with the exact token — which only a human
approving the proposal should trigger. This makes "the model changed my
infrastructure without me approving it" structurally impossible at the
tool level, rather than relying only on client-side UX conventions.

Tokens expire after a short window and can only be used once.

Every proposal and every confirm attempt (success, decline, expired,
invalid, already-used) is appended to a local JSONL audit log — so there's
a durable record of what was proposed, what was actually executed, and
when, independent of the in-memory process state.
"""

import time
import uuid
import json
import os
import subprocess
from typing import Callable
from datetime import datetime, timezone

TOKEN_EXPIRY_SECONDS = 300  # a proposal is only valid for 5 minutes
AUDIT_LOG_PATH = os.environ.get(
    "MCP_AUDIT_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "audit_log.jsonl"),
)

_pending_actions: dict[str, dict] = {}


def _audit(event: str, **fields):
    """Append a structured event to the audit log. Never raises — a logging
    failure must never block or corrupt the actual approval flow."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # audit logging is best-effort; don't let a disk issue block real operations


def propose_action(description: str, action_fn: Callable[[], str], action_type: str = "generic") -> dict:
    """
    Register a proposed state-changing action. Returns a description and a
    token — the action itself has NOT run yet.
    """
    token = str(uuid.uuid4())
    _pending_actions[token] = {
        "description": description,
        "action_fn": action_fn,
        "action_type": action_type,
        "created_at": time.time(),
        "executed": False,
    }

    _audit("proposed", token=token, description=description, action_type=action_type)

    return {
        "confirmation_token": token,
        "description": description,
        "message": (
            f"Proposed action: {description}\n"
            f"This has NOT been executed. To proceed, the user must explicitly "
            f"confirm using confirm_action(token=\"{token}\")."
        ),
    }


def confirm_action(token: str) -> str:
    """Execute a previously proposed action, if the token is valid and unexpired."""
    entry = _pending_actions.get(token)

    if entry is None:
        _audit("confirm_rejected", token=token, reason="invalid_or_unknown_token")
        return "❌ Invalid or unknown confirmation token. The action was NOT executed."

    if entry["executed"]:
        _audit("confirm_rejected", token=token, reason="already_executed", description=entry["description"])
        return "❌ This action has already been executed once. Tokens are single-use."

    age = time.time() - entry["created_at"]
    if age > TOKEN_EXPIRY_SECONDS:
        _audit("confirm_rejected", token=token, reason="expired", description=entry["description"], age_seconds=round(age))
        del _pending_actions[token]
        return "❌ This confirmation token has expired. Please propose the action again."

    entry["executed"] = True
    result = entry["action_fn"]()

    _audit(
        "confirmed_and_executed",
        token=token,
        description=entry["description"],
        action_type=entry["action_type"],
        result=result,
    )

    return f"✅ Executed: {entry['description']}\n\nResult:\n{result}"


def decline_action(token: str, reason: str = "user declined") -> str:
    """
    Explicitly record that a human declined a proposed action. Not required
    for the safety guarantee (an un-confirmed token simply expires unused),
    but declining explicitly gives a clean audit trail of "shown to a human,
    and they said no" versus "never got a response either way."
    """
    entry = _pending_actions.get(token)
    if entry is None:
        return "❌ Invalid or unknown confirmation token."

    _audit("declined", token=token, description=entry["description"], reason=reason)
    del _pending_actions[token]
    return f"Action declined and discarded: {entry['description']}"


def read_audit_log(limit: int = 50) -> list:
    """Read the most recent audit log entries — useful for a 'what has this agent done' review."""
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return [json.loads(line) for line in lines[-limit:]]


# ==================================================================
# Risky action implementations (only ever run via confirm_action)
# ==================================================================

# ---- Linux: restart a systemd service ----

def _restart_service_impl(service_name: str) -> str:
    result = subprocess.run(
        ["systemctl", "restart", service_name], capture_output=True, text=True, timeout=15
    )
    verify = subprocess.run(
        ["systemctl", "is-active", service_name], capture_output=True, text=True, timeout=5
    )
    return f"restart exit code: {result.returncode}\nservice status after restart: {verify.stdout.strip()}"


def propose_restart_service(service_name: str) -> dict:
    """Propose restarting a systemd service. Does NOT restart it yet — requires confirm_action()."""
    return propose_action(
        description=f"Restart systemd service '{service_name}'",
        action_fn=lambda: _restart_service_impl(service_name),
        action_type="linux_restart_service",
    )


# ---- Kubernetes: scale a deployment ----

def _scale_deployment_impl(deployment_name: str, namespace: str, replicas: int) -> str:
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    apps_v1 = client.AppsV1Api()
    apps_v1.patch_namespaced_deployment_scale(
        name=deployment_name,
        namespace=namespace,
        body={"spec": {"replicas": replicas}},
    )

    updated = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
    return f"Deployment '{deployment_name}' scaled. spec.replicas is now {updated.spec.replicas}."


def propose_scale_deployment(deployment_name: str, namespace: str, replicas: int) -> dict:
    """
    Propose scaling a Kubernetes Deployment to a specific replica count.
    Does NOT scale it yet — requires confirm_action(). Scaling to 0 is
    allowed (effectively stops the workload) — worth extra scrutiny before
    approving, which is exactly why this goes through the approval flow
    rather than executing immediately.
    """
    return propose_action(
        description=f"Scale deployment '{namespace}/{deployment_name}' to {replicas} replicas",
        action_fn=lambda: _scale_deployment_impl(deployment_name, namespace, replicas),
        action_type="k8s_scale_deployment",
    )


# ---- AWS: stop an EC2 instance ----

def _stop_ec2_instance_impl(instance_id: str, region: str) -> str:
    import boto3

    ec2 = boto3.client("ec2", region_name=region)
    ec2.stop_instances(InstanceIds=[instance_id])

    resp = ec2.describe_instances(InstanceIds=[instance_id])
    state = resp["Reservations"][0]["Instances"][0]["State"]["Name"]
    return f"Stop requested for {instance_id}. Current state: {state} (may take a minute to fully stop)."


def propose_stop_ec2_instance(instance_id: str, region: str = "eu-central-1") -> dict:
    """
    Propose stopping an EC2 instance. Does NOT stop it yet — requires
    confirm_action(). Stopping a production instance is exactly the kind
    of action that should never happen without an explicit human decision.
    """
    return propose_action(
        description=f"Stop EC2 instance '{instance_id}' in {region}",
        action_fn=lambda: _stop_ec2_instance_impl(instance_id, region),
        action_type="aws_stop_ec2_instance",
    )
