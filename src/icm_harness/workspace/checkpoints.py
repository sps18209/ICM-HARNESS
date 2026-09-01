import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileDigest:
    path: str
    sha256: str
    size: int


def hash_tree(
    root: str | Path, *, exclude_prefixes=(".git/", ".harness/runtime/")
) -> tuple[FileDigest, ...]:
    base = Path(root)
    result = []
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        rel = path.relative_to(base).as_posix()
        if any(rel.startswith(prefix) for prefix in exclude_prefixes):
            continue
        data = path.read_bytes()
        result.append(FileDigest(rel, sha256(data).hexdigest(), len(data)))
    return tuple(result)


def write_checkpoint(root: str | Path, output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([asdict(x) for x in hash_tree(root)], indent=2, sort_keys=True),
        encoding="utf-8",
    )
