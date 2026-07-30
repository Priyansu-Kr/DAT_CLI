import subprocess
import os
import tempfile
from typing import List, Tuple, Optional

class ADBAdapter:
    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path

    def _run(self, args: List[str]) -> Tuple[int, bytes, str]:
        cmd = [self.adb_path] + args
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            return res.returncode, res.stdout, res.stderr.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            return 127, b"", "adb binary not found"

    def is_adb_available(self) -> bool:
        code, out, _ = self._run(["version"])
        return code == 0

    def get_devices(self) -> List[str]:
        code, out, _ = self._run(["devices"])
        if code != 0:
            return []
        text = out.decode("utf-8", errors="ignore")
        devices = []
        for line in text.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def capture_screenshot(self, output_path: str, device_id: Optional[str] = None) -> Tuple[bool, str]:
        if not self.is_adb_available():
            return False, "ADB tool is not installed or available on PATH"

        devices = self.get_devices()
        if not devices:
            return False, "No active Android device or emulator detected via ADB"

        target_device = device_id or devices[0]
        cmd_prefix = ["-s", target_device] if target_device else []

        code, img_bytes, err = self._run(cmd_prefix + ["exec-out", "screencap", "-p"])
        if code == 0 and len(img_bytes) > 100 and img_bytes.startswith(b"\x89PNG"):
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_bytes)
            return True, f"Captured screenshot from device '{target_device}' -> {output_path}"

        remote_path = "/sdcard/dat_screencap.png"
        code1, _, err1 = self._run(cmd_prefix + ["shell", "screencap", "-p", remote_path])
        if code1 == 0:
            code2, _, err2 = self._run(cmd_prefix + ["pull", remote_path, output_path])
            self._run(cmd_prefix + ["shell", "rm", remote_path])
            if code2 == 0:
                return True, f"Captured screenshot from device '{target_device}' -> {output_path}"

        return False, f"Failed to capture screenshot: {err or err1 or err2}"
