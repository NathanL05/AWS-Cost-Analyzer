"""
Offline demo of the AWS Cost Analyzer.

Seeds a fake AWS account (using moto) with wasteful resources, then runs the
REAL `scan` CLI command against it. No AWS account or credentials required.

Run with:  python demo.py
"""
import os
from datetime import datetime, timedelta

# moto needs *some* credentials present, even though they are never validated.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")

import boto3
from moto import mock_aws
from freezegun import freeze_time
from click.testing import CliRunner

from cli import cli

REGION = "eu-west-1"


def seed_wasteful_account():
    """Create a realistic pile of wasted AWS resources for the scanners to find."""
    ec2 = boto3.client("ec2", region_name=REGION)

    # --- 2 stopped EC2 instances (still paying for their attached EBS disks) ---
    for instance_type in ("t3.large", "m5.xlarge"):
        resp = ec2.run_instances(
            ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType=instance_type
        )
        ec2.stop_instances(InstanceIds=[resp["Instances"][0]["InstanceId"]])

    # --- 3 unattached EBS volumes (pure waste) ---
    for size in (100, 250, 500):
        ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=size, VolumeType="gp3")

    # --- 2 old snapshots (created 120 days ago) ---
    vol = ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=200, VolumeType="gp3")["VolumeId"]
    with freeze_time(datetime.now() - timedelta(days=120)):
        ec2.create_snapshot(VolumeId=vol, Description="forgotten backup 1")
        ec2.create_snapshot(VolumeId=vol, Description="forgotten backup 2")

    # --- 3 unassociated Elastic IPs ($3.60/mo each while idle) ---
    for _ in range(3):
        ec2.allocate_address(Domain="vpc")

    # --- 2 empty S3 buckets ---
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="old-staging-logs-bucket")
    s3.create_bucket(Bucket="abandoned-backups-bucket")

    # --- 1 IAM user with an access key unused for 120 days ---
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_user(UserName="legacy-ci-user")
    with freeze_time(datetime.now() - timedelta(days=120)):
        iam.create_access_key(UserName="legacy-ci-user")


@mock_aws
def main():
    print("Seeding a fake AWS account with wasteful resources (via moto)...\n")
    seed_wasteful_account()

    runner = CliRunner()
    result = runner.invoke(
        cli, ["scan", "--region", REGION, "--json-output", "demo_report.json"]
    )
    print(result.output)
    if result.exception:
        import traceback
        traceback.print_exception(type(result.exception), result.exception, result.exception.__traceback__)


if __name__ == "__main__":
    main()
