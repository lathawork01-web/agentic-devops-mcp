"""
aws_tools.py — read-only AWS diagnostics.

Deliberately limited to Describe/List/Get calls. Nothing here can create,
modify, or delete an AWS resource.
"""

import boto3


def list_ec2_instances(region: str = "eu-central-1") -> str:
    """List EC2 instances with their state, type, and name tag."""
    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_instances()

    lines = []
    for reservation in resp["Reservations"]:
        for instance in reservation["Instances"]:
            name = next(
                (t["Value"] for t in instance.get("Tags", []) if t["Key"] == "Name"),
                "(unnamed)",
            )
            lines.append(
                f"{instance['InstanceId']}  |  {name}  |  {instance['State']['Name']}  |  {instance['InstanceType']}"
            )
    return "\n".join(lines) if lines else "No EC2 instances found."


def list_s3_buckets() -> str:
    """List S3 buckets in the account."""
    s3 = boto3.client("s3")
    resp = s3.list_buckets()
    return "\n".join(b["Name"] for b in resp["Buckets"]) or "No S3 buckets found."


def get_iam_role_policies(role_name: str) -> str:
    """List policies attached to an IAM role — useful for diagnosing permission errors."""
    iam = boto3.client("iam")
    attached = iam.list_attached_role_policies(RoleName=role_name)
    inline = iam.list_role_policies(RoleName=role_name)

    lines = ["Attached managed policies:"]
    lines += [f"  - {p['PolicyName']}" for p in attached["AttachedPolicies"]] or ["  (none)"]
    lines.append("Inline policies:")
    lines += [f"  - {name}" for name in inline["PolicyNames"]] or ["  (none)"]
    return "\n".join(lines)


def check_ecr_repository(repository_name: str, region: str = "eu-central-1") -> str:
    """Check an ECR repository's recent image tags and scan findings summary."""
    ecr = boto3.client("ecr", region_name=region)
    images = ecr.describe_images(repositoryName=repository_name, maxResults=5)

    lines = []
    for img in images.get("imageDetails", []):
        tags = ", ".join(img.get("imageTags", ["(untagged)"]))
        severity_counts = img.get("imageScanFindingsSummary", {}).get("findingSeverityCounts", {})
        lines.append(f"{tags}  |  pushed: {img.get('imagePushedAt')}  |  findings: {severity_counts}")
    return "\n".join(lines) if lines else f"No images found in {repository_name}."
