import hashlib
import os
import re
import tempfile
from pathlib import Path


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, checksum: str) -> Path:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
            raise ValueError("INVALID_CHECKSUM")
        value = checksum.removeprefix("sha256:")
        path = self.root / value[:2] / value
        if not path.parent.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ValueError("STORE_PATH_ESCAPE")
        return path

    @staticmethod
    def hash_file(path: Path) -> str:
        sha = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                sha.update(chunk)
        return "sha256:" + sha.hexdigest()

    def put(self, source: Path) -> tuple[str, Path, int]:
        sha, size = hashlib.sha256(), 0
        fd, name = tempfile.mkstemp(prefix=".staging-", dir=self.root)
        staged = Path(name)
        try:
            with os.fdopen(fd, "wb") as target, source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            checksum = "sha256:" + sha.hexdigest()
            destination = self.path(checksum)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(staged, destination)
            except FileExistsError:
                if self.hash_file(destination) != checksum:
                    raise ValueError("EXISTING_OBJECT_CHECKSUM_MISMATCH")
            if os.name == "posix":
                directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return checksum, destination, size
        finally:
            staged.unlink(missing_ok=True)
