"""Region seams: faces shared by two bounded regions on one mesh and assigned on neither side."""

from __future__ import annotations

import json
from pathlib import Path

import meshio
import numpy as np
import pytest

from blab.project_cli import main as project_main

EXAMPLE = Path(__file__).parents[1] / "examples" / "porous_layer_tube" / "porous_layer_tube.blab.json"
SEAM_Z_MM = 50.0


def _validate(capsys, project: Path) -> tuple[int, dict]:
    capsys.readouterr()
    try:
        code = project_main(["validate", str(project), "--json"], prog="blab project") or 0
    except SystemExit as exit_:
        code = exit_.code
    return code, json.loads(capsys.readouterr().out)


def test_validate_lists_the_region_seam_of_the_porous_layer_tube(capsys) -> None:
    code, summary = _validate(capsys, EXAMPLE)

    assert code == 0 and summary["valid"]
    # The 2 x 2 cell cross-section splits into 8 triangles on the shared z = 50 mm face.
    assert summary["region_seams"] == [
        {"region_ids": ["region:air", "region:layer"], "mesh_id": "mesh:tube", "face_count": 8}
    ]


def test_validate_lists_no_region_seams_for_a_single_region_project(capsys) -> None:
    code, summary = _validate(capsys, EXAMPLE.parents[1] / "filled_tube" / "filled_tube.blab.json")

    assert code == 0 and summary["region_seams"] == []


def _project_with_tagged_shared_face(tmp_path: Path, *, assigned_by: tuple[str, ...]) -> Path:
    """Copy the example with the shared face tagged as physical surface 'Partition'."""

    mesh = meshio.read(EXAMPLE.with_suffix("").with_suffix(".msh"))
    points_on_seam = np.isclose(mesh.points[:, 2], SEAM_Z_MM)
    seam_faces = []
    for block in mesh.cells:
        if block.type != "tetra":
            continue
        for tetrahedron in block.data:
            for omitted in range(4):
                face = np.delete(tetrahedron, omitted)
                if points_on_seam[face].all():
                    seam_faces.append(tuple(sorted(face)))
    triangles = np.array(sorted(set(seam_faces)))
    partition_tag = 99
    cells = [(block.type, block.data) for block in mesh.cells] + [("triangle", triangles)]
    physical = [*mesh.cell_data["gmsh:physical"], np.full(len(triangles), partition_tag)]
    field_data = {**mesh.field_data, "Partition": np.array([partition_tag, 2])}
    meshio.write(
        tmp_path / "tube.msh",
        meshio.Mesh(mesh.points, cells, cell_data={"gmsh:physical": physical}, field_data=field_data),
        file_format="gmsh22",
        binary=False,
    )

    project = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    project["imported_meshes"][0]["source_file"] = "tube.msh"
    system = project["physical_system"]
    system["meshes"][0]["file"] = "tube.msh"
    for region_id in assigned_by:
        system["boundaries"].append(
            {
                "group": {"dimension": 2, "mesh_id": "mesh:tube", "name": "Partition", "tag": None},
                "id": f"boundary:partition-{region_id}",
                "kind": "rigid",
                "name": "Partition",
                "parameters": {},
                "region_id": region_id,
            }
        )
    path = tmp_path / "tube.blab.json"
    path.write_text(json.dumps(project), encoding="utf-8")
    return path


def test_shared_face_assigned_on_both_sides_is_a_rigid_partition_not_a_seam(tmp_path: Path, capsys) -> None:
    project = _project_with_tagged_shared_face(tmp_path, assigned_by=("region:air", "region:layer"))

    code, summary = _validate(capsys, project)

    assert code == 0 and summary["region_seams"] == []


@pytest.mark.parametrize(
    ("assigned_by", "unassigned_by"), [("region:air", "region:layer"), ("region:layer", "region:air")]
)
def test_shared_face_assigned_on_one_side_is_rejected_naming_both_regions(
    tmp_path: Path, capsys, assigned_by: str, unassigned_by: str
) -> None:
    project = _project_with_tagged_shared_face(tmp_path, assigned_by=(assigned_by,))

    code, error = _validate(capsys, project)

    assert code != 0 and error["event"] == "error"
    message = error["message"]
    assert "region:air" in message and "region:layer" in message
    assert f"assigned only by region '{assigned_by}'" in message
    # The specific seam message replaces the generic coverage complaint about the other region.
    assert f"Region '{unassigned_by}' has unassigned" not in message


def test_shared_face_tagged_but_unassigned_on_both_sides_is_a_seam(tmp_path: Path, capsys) -> None:
    # Spec: shared faces without assignment become region seams, even when the mesh tags them.
    project = _project_with_tagged_shared_face(tmp_path, assigned_by=())

    code, summary = _validate(capsys, project)

    assert code == 0 and summary["valid"], summary
    assert summary["region_seams"] == [
        {"region_ids": ["region:air", "region:layer"], "mesh_id": "mesh:tube", "face_count": 8}
    ]
