"""Air-only example projects compile to the same engine request as before porous materials (5fefb98).

Each digest is the SHA-256 of the compiled request (`system_solve_request_to_dict`, keys sorted) with
mesh paths made relative to the example directory (derived meshes: to the working directory, whose
``runs/`` receives them), generated at 5fefb98 with project frequencies.
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
    "2x12_CRAM": "e5da90a84b34e6ee53f7dd3ae40cc190e36fe41b82f61aa22d26848c82ba9bc4",
    "F2B_FLH": "ab1e5538797b521f226d32660463f3899008a36307ceb6d98d9df7b954799608",
    "Multi_region_SAWMOD": "8b9e06a9cbaaf0662cbf2d8f5ff6cf3dae81e79b3fd7f90b68404a34fe688445",
    "S218BP": "a8a53871644b431a5c2c6bf47c9ed1711c3141a7a00c8bd0c1d471770ac7c5cf",
    "SKRAM": "7c487aad2abb00c3d3f730209a08baa07e16830d0d04f6f6b9453a7d9b5a76a4",
    "Simple_Sealed": "8d6f6cde6c3ab50e10060741540fe5a2a2746ad113b0284122b6bb4cf5b57239",
    "Vented_Sub": "3ca2ee5872e0b534cad3e4b5535365e2bd7b94873da4d82a8e1aceeb48c3f7dd",
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
