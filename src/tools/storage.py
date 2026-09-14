"""Explicit S3 archival of public fixtures and synthetic evidence files."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from src.domain.stored_file import StoredFile

MAX_FILE_BYTES = 10 * 1024 * 1024


def store_file(path: Path, *, bucket: str, prefix: str, region: str = "eu-west-2") -> StoredFile:
    """Archive one caller-selected public/synthetic file; never set a public ACL.

    Keys include the full content hash. Conditional creation prevents replacing
    an existing object. A duplicate must pass byte verification before reuse.
    No bucket creation, policy change, or live-runtime attachment occurs here.
    """
    if not bucket.strip() or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", prefix):
        raise ValueError("Specify a bucket and a simple slash-separated archive prefix.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", path.name):
        raise ValueError("Archive filenames may contain only letters, numbers, dots, _ and -.")
    with path.open("rb") as source:
        data = source.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Archive file exceeds the 10 MiB limit.")
    digest = hashlib.sha256(data).hexdigest()
    reference = StoredFile(
        bucket=bucket, key=f"{prefix}/{digest}/{path.name}", sha256=digest, size=len(data)
    )
    client = boto3.client("s3", region_name=region)
    try:
        client.put_object(
            Bucket=bucket,
            Key=reference.key,
            Body=data,
            ContentType=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            ServerSideEncryption="AES256",
            Metadata={"sha256": digest},
            IfNoneMatch="*",
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "PreconditionFailed":
            raise
        read_stored_file(reference, region=region)
    return reference


def read_stored_file(reference: StoredFile, *, region: str = "eu-west-2") -> bytes:
    """Retrieve bytes only if their size and SHA-256 match the saved reference."""
    response = boto3.client("s3", region_name=region).get_object(
        Bucket=reference.bucket, Key=reference.key
    )
    body = response["Body"]
    try:
        data: bytes = body.read(reference.size + 1)
    finally:
        body.close()
    if len(data) != reference.size or hashlib.sha256(data).hexdigest() != reference.sha256:
        raise ValueError("Stored file does not match its recorded size and SHA-256.")
    return data
