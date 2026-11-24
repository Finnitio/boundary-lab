"""Air-only example projects compile to the same engine request as without porous materials.

Each digest is the SHA-256 of the compiled request (`system_solve_request_to_dict`, keys sorted) with
mesh paths made relative to the example directory (derived meshes: to the working directory, whose
``runs/`` receives them), generated at 5fefb98 with project frequencies and regenerated for upstream
v0.5.1 (c3d290b, no porous code), which compiles the same requests as this branch.
A change here means air-only requests changed on the wire; regenerate only for an intended change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from blab.headless import load_headless_project, load_headless_solve_spec, prepare_headless_solve
from blab.system_contract import system_solve_request_to_dict

EXAMPLES = Path(__file__).parents[1] / "examples"
AIR_ONLY_REQUEST_SHA256 = {
    "2x12_CRAM": "75d71f548091aa0d74b6534c3d8bbc7aa3465a4462aad50b9ce713c2f3cec945",
    "F2B_FLH": "2925077947df594f05edfae92baef27f6e427b0a999620e3d4778c09b087ae7b",
    "Multi_region_SAWMOD": "513ec45701f7e6072c38e492b2e5a22952b4b93337d4e80bca6687601dc1e73e",
    "S218BP": "1b3dc16acf90094dc369d29c296adce1982789acec2bfffc253ae82c14eab7a9",
    "SKRAM": "61026221f04d955584cebd3b63f69c2f6ad267fda771dd9dbe7240eda3927b70",
    "Simple_Sealed": "22016d71fdbc02607fed67b51225d52e223c1019b27d64c0765c1a619e2059fe",
    "Vented_Sub": "a95a559912dcadc8b6d5f502ca173d720c9e11b59d39bc128a68d7e34a7c4643",
    "compression_driver": "13a0e9c4949c5a36d68dd5062028346e763444e8917e215ffa9b54eff72aed62",
}


def _relative_mesh_paths(value, directories: tuple[Path, ...]):
    if isinstance(value, dict):
        return {key: _relative_mesh_paths(item, directories) for key, item in value.items()}
    if isinstance(value, list):
        return [_relative_mesh_paths(item, directories) for item in value]
    if isinstance(value, str) and value.endswith(".msh") and Path(value).is_absolute():
        path = Path(value).resolve()
        directory = next(directory for directory in directories if path.is_relative_to(directory))
        return path.relative_to(directory).as_posix()
    return value


def compiled_request_sha256(path: Path) -> str:
    prepared = prepare_headless_solve(
        load_headless_project(path), load_headless_solve_spec(None), backend_id="beat_cpu"
    )
    directories = (path.parent.resolve(), Path.cwd().resolve())
    request = _relative_mesh_paths(system_solve_request_to_dict(prepared.request), directories)
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("example", sorted(AIR_ONLY_REQUEST_SHA256))
def test_air_only_example_compiles_to_the_pre_porous_request(
    example: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # derived (stitched) meshes go to ./runs, not into the checkout
    (path,) = (EXAMPLES / example).glob("*.blab.json")

    assert compiled_request_sha256(path) == AIR_ONLY_REQUEST_SHA256[example]
