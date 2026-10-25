import os
import subprocess
import sys
from pathlib import Path


def test_cli_converts_real_bytes_and_refuses_to_overwrite(tmp_path):
    target = tmp_path / "from the craft.nbt"
    command = [
        sys.executable,
        "-m",
        "fromthecraft",
        "convert",
        "tests/fixtures/asymmetric.blueprint",
        str(target),
        "--scale",
        "0.5",
    ]
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert target.read_bytes()[:2] == b"\x1f\x8b"
    original = target.read_bytes()
    completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert completed.returncode != 0
    assert target.read_bytes() == original


def test_cli_optimized_conversion_retains_exact_file(tmp_path):
    target = tmp_path / "optimized.nbt"
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    command = [sys.executable, "-m", "fromthecraft", "convert", "tests/fixtures/asymmetric.blueprint", str(target)]
    result = subprocess.run(command + ["--optimized-conversion"], env=env, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    from fromthecraft.convert import convert, read_file

    expected = convert(read_file(Path("tests/fixtures/asymmetric.blueprint").read_bytes(), "blueprint"), "nbt")
    assert target.read_bytes() == expected.content


def test_cli_converts_minecraft_back_to_blueprint(tmp_path):
    from fromthecraft.convert import convert
    from fromthecraft.ftd import read_blueprint

    source = tmp_path / "independent.nbt"
    source.write_bytes(
        convert(read_blueprint(Path("tests/fixtures/asymmetric.blueprint").read_bytes()), "nbt").content
    )
    target = tmp_path / "static.blueprint"
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    completed = subprocess.run(
        [sys.executable, "-m", "fromthecraft", "convert", str(source), str(target)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert len(read_blueprint(target.read_bytes()).parts) == 7


def test_cli_hollow_option_writes_an_exterior_shell(tmp_path):
    import json
    from fromthecraft.minecraft import read_structure

    document = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    document["Blueprint"].update(BLP=["0,0,0"], BLR=[0], BCI=[0], BlockIds=[0], SCs=[])
    source, target = tmp_path / "cube.blueprint", tmp_path / "shell.nbt"
    source.write_text(json.dumps(document))
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "fromthecraft",
            "convert",
            str(source),
            str(target),
            "--scale",
            "4",
            "--hollow",
            "--shell-thickness",
            "1",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert len(read_structure(target.read_bytes()).parts) == 56
