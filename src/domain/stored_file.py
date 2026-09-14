"""Portable reference to a content-addressed evidence file."""

from pydantic import BaseModel, ConfigDict, Field


class StoredFile(BaseModel):
    """Byte identity, not a claim that the file is a certified audit archive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket: str = Field(min_length=3)
    key: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=10 * 1024 * 1024)
