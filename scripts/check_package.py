"""Build and install a wheel, then check its CLI outside the source checkout.

This check uses no API, credentials, third-party datasets or network downloads.
An isolated venv deliberately installs the wheel without runtime dependencies:
CLI discovery/help and the missing-workspace guard use only the standard library.
Normal users should install the wheel with its declared dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("semiconductor_logistics", "notice_benchmark", "notice_facts", "real_notice_eval", "decision_benchmark", "coupled_decision", "budgeted_decision", "query_policy", "query_ppo", "query_study", "query_components", "shared", "scripts")


def run(command: list[str], cwd: Path, *, expected: int = 0) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False,
                            env={key: value for key, value in os.environ.items()
                                 if key not in {"PYTHONPATH", "PYTHONHOME"}})
    if result.returncode != expected:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n"
                           f"{result.stdout}{result.stderr}")
    return result.stdout + result.stderr


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="semiconductor-package-") as temporary:
        temporary_root = Path(temporary)
        source, wheels, outside = (temporary_root / name for name in ("source", "wheels", "outside"))
        source.mkdir()
        outside.mkdir()
        for filename in ("pyproject.toml", "README.md"):
            shutil.copy2(ROOT / filename, source / filename)
        for package in PACKAGES:
            shutil.copytree(ROOT / package, source / package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
             "--wheel-dir", str(wheels), str(source)], outside)
        wheel_files = list(wheels.glob("*.whl"))
        if len(wheel_files) != 1:
            raise RuntimeError(f"Expected one project wheel, found {len(wheel_files)}")
        environment = temporary_root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        binary_dir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binary_dir / ("python.exe" if os.name == "nt" else "python")
        command = binary_dir / ("semiconductor-logistics.exe" if os.name == "nt" else "semiconductor-logistics")
        run([str(python), "-m", "pip", "install", "--no-deps", str(wheel_files[0])], outside)
        for invocation in ([str(command), "--help"],
                           [str(python), "-I", "-m", "semiconductor_logistics", "--help"],
                           [str(command), "api", "--help"],
                           [str(command), "real-notices", "--help"],
                           [str(command), "decision-audit", "--help"],
                           [str(command), "coupled-audit", "--help"],
                           [str(command), "scale-audit", "--help"],
                           [str(command), "query-budget", "--help"],
                           [str(command), "query-bc", "--help"],
                           [str(command), "query-ppo", "--help"],
                           [str(command), "query-study", "--help"],
                           [str(command), "query-components", "--help"],
                           [str(command), "notice-facts", "--help"],
                           [str(command), "generate", "--help"]):
            output = run(invocation, outside)
            if "usage:" not in output:
                raise RuntimeError("Installed CLI did not display help")
        output = run([str(command), "optimize", "--smoke"], outside, expected=2)
        if "--workspace" not in output or "not bundled" not in output:
            raise RuntimeError("Installed CLI did not explain its workspace requirement")
        imports = "import importlib.util; " + "; ".join(
            f"assert importlib.util.find_spec('{package}') is not None" for package in PACKAGES)
        run([str(python), "-I", "-c", imports], outside)
    print("Wheel installed; console/module help and workspace guard passed outside the checkout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
