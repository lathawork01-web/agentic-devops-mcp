"""
server.py — Agentic DevOps MCP Server

Exposes diagnostic tools across Linux, AWS, and Kubernetes, plus a
human-in-the-loop propose/confirm mechanism for anything that changes
infrastructure state.

    User → AI Agent → MCP → { Linux | AWS | K8s }

Read-only tools (status checks, logs, listings) execute immediately.
State-changing tools (currently: restart_service) are split into a
propose step and a separate confirm step — see approval.py for why.
"""

from mcp.server.fastmcp import FastMCP
import json

from tools import linux_tools, aws_tools, k8s_tools
import approval

mcp = FastMCP("agentic-devops")

# ---------------- Linux (read-only) ----------------

@mcp.tool()
def check_service_status(service_name: str) -> str:
    """Check whether a systemd service is active and its recent state."""
    return linux_tools.check_service_status(service_name)


@mcp.tool()
def get_service_logs(service_name: str, lines: int = 50) -> str:
    """Get recent journalctl logs for a systemd service."""
    return linux_tools.get_service_logs(service_name, lines)


@mcp.tool()
def check_port(port: int) -> str:
    """Check what's listening on a given port."""
    return linux_tools.check_port(port)


@mcp.tool()
def check_disk_usage() -> str:
    """Check disk usage across mounted filesystems."""
    return linux_tools.check_disk_usage()


@mcp.tool()
def check_memory_usage() -> str:
    """Check system memory usage."""
    return linux_tools.check_memory_usage()


# ---------------- AWS (read-only) ----------------

@mcp.tool()
def list_ec2_instances(region: str = "eu-central-1") -> str:
    """List EC2 instances with state, type, and name."""
    return aws_tools.list_ec2_instances(region)


@mcp.tool()
def list_s3_buckets() -> str:
    """List S3 buckets in the account."""
    return aws_tools.list_s3_buckets()


@mcp.tool()
def get_iam_role_policies(role_name: str) -> str:
    """List policies attached to an IAM role — useful for diagnosing permission errors."""
    return aws_tools.get_iam_role_policies(role_name)


@mcp.tool()
def check_ecr_repository(repository_name: str, region: str = "eu-central-1") -> str:
    """Check recent image tags and vulnerability scan findings in an ECR repository."""
    return aws_tools.check_ecr_repository(repository_name, region)


# ---------------- Kubernetes (read-only) ----------------

@mcp.tool()
def get_pods(namespace: str = "default") -> str:
    """List pods in a namespace, flagging unhealthy ones."""
    return k8s_tools.get_pods(namespace)


@mcp.tool()
def describe_pod(pod_name: str, namespace: str = "default") -> str:
    """Detailed status for a specific pod."""
    return k8s_tools.describe_pod(pod_name, namespace)


@mcp.tool()
def get_pod_logs(pod_name: str, namespace: str = "default", tail_lines: int = 50) -> str:
    """Recent logs from a pod."""
    return k8s_tools.get_pod_logs(pod_name, namespace, tail_lines)


@mcp.tool()
def get_deployment_status(deployment_name: str, namespace: str = "default") -> str:
    """Replica counts for a Deployment."""
    return k8s_tools.get_deployment_status(deployment_name, namespace)


# ---------------- State-changing actions (human-in-the-loop) ----------------

@mcp.tool()
def propose_restart_service(service_name: str) -> dict:
    """
    Propose restarting a systemd service. This does NOT restart it —
    it returns a confirmation_token that must be passed to confirm_action()
    before anything actually happens. Always show the proposal to the user
    and wait for their explicit approval before calling confirm_action.
    """
    return approval.propose_restart_service(service_name)


@mcp.tool()
def propose_scale_deployment(deployment_name: str, namespace: str = "default", replicas: int = 1) -> dict:
    """
    Propose scaling a Kubernetes Deployment to a specific replica count.
    This does NOT scale it — returns a confirmation_token that must be
    passed to confirm_action() before anything actually happens.
    """
    return approval.propose_scale_deployment(deployment_name, namespace, replicas)


@mcp.tool()
def propose_stop_ec2_instance(instance_id: str, region: str = "eu-central-1") -> dict:
    """
    Propose stopping an EC2 instance. This does NOT stop it — returns a
    confirmation_token that must be passed to confirm_action() before
    anything actually happens.
    """
    return approval.propose_stop_ec2_instance(instance_id, region)


@mcp.tool()
def confirm_action(confirmation_token: str) -> str:
    """
    Execute a previously proposed action using its confirmation token.
    Only call this after the user has explicitly approved the proposed
    action shown to them — never call this automatically right after
    a propose_* call.
    """
    return approval.confirm_action(confirmation_token)


@mcp.tool()
def decline_action(confirmation_token: str, reason: str = "user declined") -> str:
    """Explicitly decline a proposed action, discarding it and recording why in the audit log."""
    return approval.decline_action(confirmation_token, reason)


@mcp.tool()
def get_audit_log(limit: int = 20) -> str:
    """Get the most recent audit log entries — every proposal, confirmation, decline, and rejection."""
    entries = approval.read_audit_log(limit)
    if not entries:
        return "No audit log entries yet."
    return "\n".join(json.dumps(e) for e in entries)


if __name__ == "__main__":
    mcp.run()
