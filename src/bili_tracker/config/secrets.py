from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecretValue:
    """A value whose repr and string form cannot disclose the secret."""

    value: str

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    @property
    def is_set(self) -> bool:
        return bool(self.value)
