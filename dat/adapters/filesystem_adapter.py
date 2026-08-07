import os
import shutil
import tempfile
from typing import Optional, List

class FilesystemAdapter:
    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def is_file(self, path: str) -> bool:
        return os.path.isfile(path)

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def ensure_dir(self, dir_path: str) -> None:
        os.makedirs(dir_path, exist_ok=True)

    def copy_file(self, src: str, dst: str) -> str:
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            self.ensure_dir(dst_dir)
        return shutil.copy2(src, dst)

    def read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def write_text(self, path: str, content: str) -> None:
        dst_dir = os.path.dirname(path)
        if dst_dir:
            self.ensure_dir(dst_dir)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_text_atomic(self, path: str, content: str) -> None:
        """Write via a temp file + rename so a crash/full disk mid-write can
        never leave a half-written (unparseable) file behind."""
        dst_dir = os.path.dirname(path) or "."
        self.ensure_dir(dst_dir)
        fd, tmp_path = tempfile.mkstemp(dir=dst_dir, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def remove_file(self, path: str) -> bool:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False

    def list_files(self, dir_path: str, extensions: Optional[List[str]] = None) -> List[str]:
        if not self.exists(dir_path):
            return []
        files = []
        for root, _, filenames in os.walk(dir_path):
            for fn in filenames:
                if extensions:
                    if any(fn.lower().endswith(ext.lower()) for ext in extensions):
                        files.append(os.path.join(root, fn))
                else:
                    files.append(os.path.join(root, fn))
        return sorted(files)
