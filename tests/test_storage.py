"""S3 archival boundaries verified without real AWS calls."""

import hashlib
import io
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from src.domain.stored_file import StoredFile
from src.tools.storage import MAX_FILE_BYTES, read_stored_file, store_file


def reference(data: bytes) -> StoredFile:
    digest = hashlib.sha256(data).hexdigest()
    return StoredFile(
        bucket="synthetic-archive",
        key=f"fixtures/{digest}/sample.json",
        sha256=digest,
        size=len(data),
    )


def test_upload_is_conditional_encrypted_and_content_addressed(tmp_path: Path) -> None:
    path = tmp_path / "sample.json"
    path.write_bytes(b'{"items": []}')
    with patch("src.tools.storage.boto3.client") as factory:
        receipt = store_file(path, bucket="synthetic-archive", prefix="fixtures")
        params = factory.return_value.put_object.call_args.kwargs
        assert receipt == reference(path.read_bytes())
        assert params["IfNoneMatch"] == "*"
        assert params["ServerSideEncryption"] == "AES256"
        assert params["Body"] == path.read_bytes()
        assert "ACL" not in params


def test_duplicate_requires_verified_existing_bytes(tmp_path: Path) -> None:
    path = tmp_path / "sample.json"
    path.write_bytes(b"{}")
    client = Mock()
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}}, "PutObject"
    )
    client.get_object.return_value = {"Body": StreamingBody(io.BytesIO(b"{}"), 2)}
    with patch("src.tools.storage.boto3.client", return_value=client):
        assert store_file(path, bucket="synthetic-archive", prefix="fixtures") == reference(b"{}")
        client.get_object.assert_called_once()


@pytest.mark.parametrize("stored", [b"bad", b"short", b"expected with trailing bytes"])
def test_read_rejects_corrupt_or_wrong_length_bytes(stored: bytes) -> None:
    with patch("src.tools.storage.boto3.client") as factory:
        body = StreamingBody(io.BytesIO(stored), len(stored))
        factory.return_value.get_object.return_value = {"Body": body}
        with pytest.raises(ValueError, match="SHA-256"):
            read_stored_file(reference(b"expected"))
        assert body._raw_stream.closed


def test_denied_upload_is_not_reported_as_success(tmp_path: Path) -> None:
    path = tmp_path / "sample.json"
    path.write_bytes(b"{}")
    with patch("src.tools.storage.boto3.client") as factory:
        factory.return_value.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "PutObject"
        )
        with pytest.raises(ClientError):
            store_file(path, bucket="synthetic-archive", prefix="fixtures")


def test_oversized_file_rejected_before_aws(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with patch("src.tools.storage.boto3.client") as factory:
        with pytest.raises(ValueError, match="10 MiB"):
            store_file(path, bucket="synthetic-archive", prefix="fixtures")
        factory.assert_not_called()


def test_invalid_prefix_rejected_before_aws(tmp_path: Path) -> None:
    with patch("src.tools.storage.boto3.client") as factory:
        with pytest.raises(ValueError, match="prefix"):
            store_file(tmp_path / "sample.json", bucket="synthetic-archive", prefix="../secret")
        factory.assert_not_called()
