"""
k8s_tools.py — read-only Kubernetes diagnostics.

Same pattern as the other two tool modules: get/list/describe/logs only.
Scaling and restarts live behind the approval flow in approval.py.
"""

from kubernetes import client, config


def _get_api():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api()


def get_pods(namespace: str = "default") -> str:
    """List pods in a namespace with status and restart count, flagging unhealthy ones."""
    v1, _ = _get_api()
    pods = v1.list_namespaced_pod(namespace=namespace)

    lines = []
    for pod in pods.items:
        restarts = max(
            (cs.restart_count for cs in (pod.status.container_statuses or [])), default=0
        )
        flag = " ⚠️ UNHEALTHY" if pod.status.phase not in ("Running", "Succeeded") or restarts > 3 else ""
        lines.append(f"{pod.metadata.name}  |  {pod.status.phase}  |  restarts: {restarts}{flag}")
    return "\n".join(lines) if lines else f"No pods found in namespace '{namespace}'."


def describe_pod(pod_name: str, namespace: str = "default") -> str:
    """Detailed status for a specific pod."""
    v1, _ = _get_api()
    pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)

    lines = [f"Pod: {pod.metadata.name}", f"Phase: {pod.status.phase}"]
    for cs in pod.status.container_statuses or []:
        state = "running"
        if cs.state.waiting:
            state = f"waiting ({cs.state.waiting.reason})"
        elif cs.state.terminated:
            state = f"terminated ({cs.state.terminated.reason})"
        lines.append(f"  {cs.name}: {state}, restarts={cs.restart_count}")
    return "\n".join(lines)


def get_pod_logs(pod_name: str, namespace: str = "default", tail_lines: int = 50) -> str:
    """Recent logs from a pod."""
    v1, _ = _get_api()
    try:
        return v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=tail_lines)
    except client.ApiException as e:
        return f"(could not fetch logs: {e.reason})"


def get_deployment_status(deployment_name: str, namespace: str = "default") -> str:
    """Replica counts for a Deployment."""
    _, apps_v1 = _get_api()
    dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
    return (
        f"{deployment_name}: desired={dep.spec.replicas}, "
        f"available={dep.status.available_replicas or 0}, "
        f"unavailable={dep.status.unavailable_replicas or 0}"
    )
