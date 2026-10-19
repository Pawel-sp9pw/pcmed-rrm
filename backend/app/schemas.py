import hashlib
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import settings


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Name(Input):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")


class Enroll(Input):
    token: str = Field(min_length=32, max_length=200)
    hostname: str = Field(min_length=1, max_length=120)
    os_version: str = Field(min_length=1, max_length=200)


class Heartbeat(Input):
    agent_version: str = Field(min_length=1, max_length=50)


class DefinitionInput(Name):
    kind: Literal["msi", "exe", "bat", "powershell"]
    url: str | None = Field(default=None, max_length=2048)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    script: str | None = Field(default=None, min_length=1, max_length=65536)
    arguments: list[str] = Field(default_factory=list, max_length=64)
    timeout_seconds: int = Field(default=600, ge=10, le=3600)

    @model_validator(mode="after")
    def validate_spec(self):
        if any(len(argument) > 2048 or any(char in argument for char in "\x00\r\n") for argument in self.arguments):
            raise ValueError("Invalid argument")
        if self.kind in {"msi", "exe"}:
            parsed = urlsplit(self.url or "")
            hosts = {host.strip().lower() for host in settings().artifact_hosts.split(",") if host.strip()}
            if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("Installer must have an allowlisted HTTPS URL")
            if not self.sha256 or self.script is not None:
                raise ValueError("Installer requires SHA-256 and no inline script")
            self.sha256 = self.sha256.lower()
        else:
            if self.script is None or self.url is not None or self.arguments or self.sha256 is not None:
                raise ValueError("Scripts require inline content and no URL, arguments or custom hash")
            content = self.script.encode("utf-8")
            if self.kind == "powershell":
                content = b"\xef\xbb\xbf" + content
            self.sha256 = hashlib.sha256(content).hexdigest()
        return self


class Targets(Input):
    device_ids: list[str] = Field(min_length=1, max_length=100)


class Dispatch(Targets):
    definition_id: str


class Message(Targets):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class Result(Input):
    claim: str = Field(min_length=36, max_length=36)
    state: Literal["succeeded", "failed", "unknown"]
    exit_code: int | None = Field(default=None, ge=-2147483648, le=2147483647)
    output: str = Field(default="", max_length=32768)
