from __future__ import annotations

from pathlib import Path


class PathContainmentError(ValueError):
    pass


def resolve_contained(root: Path, candidate: Path | str, *, allow_missing: bool = True) -> Path:
    root_resolved = root.expanduser().resolve(strict=True)
    candidate_path = Path(candidate).expanduser()
    candidate_path = (
        candidate_path if candidate_path.is_absolute() else root_resolved / candidate_path
    )
    resolved = candidate_path.expanduser().resolve(strict=not allow_missing)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PathContainmentError("path is outside the configured root") from exc
    return resolved
