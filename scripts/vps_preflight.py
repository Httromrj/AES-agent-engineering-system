"""Read-only inventory helper for an operator to run on the target VPS."""
import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def command(args, timeout=5):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def inventory(disk_path="/"):
    data = {"os": platform.platform(), "architecture": platform.machine(), "cpu_count": os.cpu_count(),
            "python": platform.python_version(), "disk_path": str(disk_path),
            "warnings": ["Review this infrastructure inventory locally before sharing it.",
                         "This cannot inspect Google Cloud firewall rules, billing, backups, or account IAM."]}
    release = Path("/etc/os-release")
    if release.is_file():
        for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("ID=", "VERSION_ID=", "PRETTY_NAME=")):
                key, value = line.split("=", 1)
                data.setdefault("os_release", {})[key] = value.strip('"')
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values = {}
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("MemTotal:", "MemAvailable:")):
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
        data["memory_bytes"] = values
    try:
        usage = shutil.disk_usage(disk_path)
        data["disk_bytes"] = {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        data["disk_bytes"] = "unavailable"
    services = command(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"])
    data["running_services"] = [line.split()[0] for line in services.splitlines() if line.split()]
    listeners = command(["ss", "-ltnH"])
    data["listening_tcp_sockets"] = [" ".join(line.split()[:4]) for line in listeners.splitlines() if line.split()]
    data["container_tools"] = {name: shutil.which(name) is not None for name in ("docker", "podman", "gcloud")}
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/cpu.max"):
        candidate = Path(path)
        if candidate.is_file():
            try:
                data.setdefault("cgroup_limits", {})[path] = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                pass
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk-path", default="/", help="Filesystem path whose capacity to report")
    parser.add_argument("--output", type=Path, help="Optional local JSON output path; file may contain infrastructure details")
    args = parser.parse_args()
    result = json.dumps(inventory(args.disk_path), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
        print(f"Inventory written locally: {args.output}")
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
