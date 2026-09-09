from __future__ import annotations


class DomainError(Exception):
    """Base class for errors that are safe to map to stable API codes."""


class InvalidTransition(DomainError):
    def __init__(self, entity: str, current: str, target: str) -> None:
        self.code = "domain.invalid_transition"
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(f"{entity} cannot transition from {current} to {target}")


class InvariantViolation(DomainError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ManifestError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
