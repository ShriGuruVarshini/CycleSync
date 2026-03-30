"""
seed_config.py — Run once after `sam deploy` to seed the JWT secret
into the cyclesync-config DynamoDB table.

Usage:
    python scripts/seed_config.py                        # dev (default)
    python scripts/seed_config.py --env prod             # prod
    python scripts/seed_config.py --secret "mysecret"    # custom secret
    python scripts/seed_config.py --region us-west-2     # custom region
"""

import argparse
import secrets
import boto3
from botocore.exceptions import ClientError


def seed(env: str, region: str, secret: str | None) -> None:
    table_name = f"cyclesync-config-{env}"
    jwt_secret = secret or secrets.token_hex(32)  # 64-char random hex if not provided

    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)

    # Check if secret already exists — don't overwrite unless forced
    try:
        resp = table.get_item(Key={"config_key": "jwt_secret"})
        if "Item" in resp:
            print(f"[INFO] jwt_secret already exists in {table_name}. Skipping.")
            print("       Use --force to overwrite.")
            return
    except ClientError as e:
        print(f"[ERROR] Could not read from {table_name}: {e.response['Error']['Message']}")
        raise

    # Write the secret
    table.put_item(Item={
        "config_key": "jwt_secret",
        "value": jwt_secret,
        "description": "HMAC-SHA256 secret used to sign and verify JWT session tokens",
    })

    print(f"[OK] jwt_secret seeded into {table_name}")
    print(f"     Secret (save this somewhere safe): {jwt_secret}")


def force_overwrite(env: str, region: str, secret: str | None) -> None:
    table_name = f"cyclesync-config-{env}"
    jwt_secret = secret or secrets.token_hex(32)

    ddb = boto3.resource("dynamodb", region_name=region)
    table = ddb.Table(table_name)

    table.put_item(Item={
        "config_key": "jwt_secret",
        "value": jwt_secret,
        "description": "HMAC-SHA256 secret used to sign and verify JWT session tokens",
    })

    print(f"[OK] jwt_secret overwritten in {table_name}")
    print(f"     New secret: {jwt_secret}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed CycleSync config into DynamoDB")
    parser.add_argument("--env", default="dev", choices=["dev", "staging", "prod"],
                        help="Deployment environment (default: dev)")
    parser.add_argument("--region", default="us-east-1",
                        help="AWS region (default: us-east-1)")
    parser.add_argument("--secret", default=None,
                        help="Custom JWT secret string (auto-generated if omitted)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing secret if present")
    args = parser.parse_args()

    if args.force:
        force_overwrite(args.env, args.region, args.secret)
    else:
        seed(args.env, args.region, args.secret)
