"""Normalize a source distribution for reproducible release comparison."""

from __future__ import annotations

import gzip
import io
import os
import sys
import tarfile
from pathlib import Path
from tempfile import NamedTemporaryFile


def normalize(path: Path) -> None:
    """Rewrite one gzip-compressed tarball with deterministic metadata."""
    with tarfile.open(path, mode="r:gz") as source:
        members = sorted(source.getmembers(), key=lambda member: member.name)
        with NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            with (
                gzip.GzipFile(
                    fileobj=temporary, mode="wb", filename="", mtime=0
                ) as compressed,
                tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
                ) as target,
            ):
                for member in members:
                    info = tarfile.TarInfo(member.name)
                    info.type = member.type
                    info.mode = member.mode
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.linkname = member.linkname
                    if member.isfile():
                        data = source.extractfile(member)
                        if data is None:
                            raise RuntimeError(
                                f"cannot read regular file {member.name}"
                            )
                        payload = data.read()
                        info.size = len(payload)
                        target.addfile(info, io.BytesIO(payload))
                    else:
                        info.size = 0
                        target.addfile(info)
    os.replace(temporary_path, path)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: normalize_sdist.py ARCHIVE [ARCHIVE ...]")
    for argument in argv[1:]:
        normalize(Path(argument))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
