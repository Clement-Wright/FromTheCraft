import importlib.metadata
import json
import shutil
import sys
from packaging.requirements import Requirement
from pathlib import Path


def main():
    destination = Path("build/THIRD_PARTY_LICENSES")
    destination.mkdir(parents=True, exist_ok=True)
    packages = [
        "numpy",
        "nbtlib",
        "litemapy",
        "fastapi",
        "uvicorn",
        "python-multipart",
        "pydantic",
        "pydantic-core",
        "starlette",
        "anyio",
        "click",
        "h11",
        "typing-extensions",
        "annotated-types",
        "typing-inspection",
        "idna",
        "pyinstaller",
    ]
    pending = ["UnityPy"]
    while pending:
        name = pending.pop()
        if name in packages:
            continue
        packages.append(name)
        for raw in importlib.metadata.requires(name) or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    for name in packages:
        distribution = importlib.metadata.distribution(name)
        folder = destination / name
        folder.mkdir(exist_ok=True)
        for entry in distribution.files or []:
            if "license" in str(entry).lower() or "copying" in str(entry).lower():
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    target = folder / str(entry).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        (folder / "METADATA.txt").write_text(
            distribution.read_text("METADATA") or f"{name} {distribution.version}", encoding="utf-8"
        )
    for name in ["react", "react-dom", "scheduler", "three", "minecraft-data"]:
        folder = Path("ui/node_modules") / name
        output = destination / name
        output.mkdir(exist_ok=True)
        package = json.loads((folder / "package.json").read_text())
        (output / "version.txt").write_text(f"{name} {package['version']}\n", encoding="utf-8")
        for source in folder.iterdir():
            if source.is_file() and ("license" in source.name.lower() or "copying" in source.name.lower()):
                shutil.copyfile(source, output / source.name)
    shutil.copyfile("src/fromthecraft/data/FTD-CATALOG-LICENSE.txt", destination / "FTD-CATALOG-LICENSE.txt")
    shutil.copyfile("COPYING", destination / "FromTheCraft-COPYING")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copyfile(python_license, destination / "Python-LICENSE.txt")


if __name__ == "__main__":
    main()
