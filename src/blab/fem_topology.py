"""Topology helpers for physical-volume FEM boundary ownership."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

import meshio
import numpy as np

_TETRAHEDRON_TYPES = {"tetra", "tetra4", "tetra10"}
_TRIANGLE_TYPES = {"triangle", "triangle3", "triangle6"}


Face = tuple[int, int, int]


def selected_volume_surface_tags(
    mesh: meshio.Mesh,
    selected_volume_tags: Iterable[int],
) -> frozenset[int]:
    """Return tagged triangle groups on the boundary of selected tetrahedra.

    The operation mirrors the Julia FEM volume restriction: faces shared by
    two selected tetrahedra are internal, while faces occurring once are
    retained only when an explicit physical triangle exists on that face.
    """

    exterior_faces = selected_volume_exterior_faces(mesh, selected_volume_tags)
    return frozenset(
        tag for face, tags in triangle_tags_by_face(mesh).items() if face in exterior_faces for tag in tags
    )


def selected_volume_exterior_faces(
    mesh: meshio.Mesh,
    selected_volume_tags: Iterable[int],
) -> frozenset[Face]:
    """Return the exterior faces (sorted corner-vertex triples) of the selected tetrahedra."""

    selected_tags = {int(tag) for tag in selected_volume_tags}
    if not selected_tags:
        raise ValueError("Select at least one physical FEM volume tag.")
    face_counts: Counter[Face] = Counter()
    selected_tetrahedron_count = 0
    for block, raw_tags in zip(mesh.cells, _physical_blocks(mesh), strict=True):
        if block.type not in _TETRAHEDRON_TYPES:
            continue
        tetrahedra = np.asarray(block.data, dtype=np.int64)
        tags = np.asarray(raw_tags, dtype=np.int64)
        if tetrahedra.ndim != 2 or tetrahedra.shape[1] < 4 or tags.shape != (tetrahedra.shape[0],):
            raise ValueError("FEM mesh physical-volume tags do not align with tetrahedra.")
        for tetrahedron in tetrahedra[np.isin(tags, tuple(selected_tags)), :4]:
            selected_tetrahedron_count += 1
            a, b, c, d = map(int, tetrahedron)
            face_counts.update(
                (
                    tuple(sorted((a, b, c))),
                    tuple(sorted((a, b, d))),
                    tuple(sorted((a, c, d))),
                    tuple(sorted((b, c, d))),
                )
            )
    if selected_tetrahedron_count == 0:
        requested = ", ".join(map(str, sorted(selected_tags)))
        raise ValueError(f"Selected FEM volume tags contain no tetrahedra: {requested}.")
    return frozenset(face for face, count in face_counts.items() if count == 1)


def triangle_tags_by_face(mesh: meshio.Mesh) -> dict[Face, frozenset[int]]:
    """Map each physical triangle's face (sorted corner-vertex triple) to its surface tags."""

    tags_by_face: dict[Face, set[int]] = {}
    for block, raw_tags in zip(mesh.cells, _physical_blocks(mesh), strict=True):
        if block.type not in _TRIANGLE_TYPES:
            continue
        triangles = np.asarray(block.data, dtype=np.int64)
        tags = np.asarray(raw_tags, dtype=np.int64)
        if triangles.ndim != 2 or triangles.shape[1] < 3 or tags.shape != (triangles.shape[0],):
            raise ValueError("FEM mesh physical-surface tags do not align with triangles.")
        for triangle, tag in zip(triangles[:, :3], tags, strict=True):
            tags_by_face.setdefault(tuple(sorted(map(int, triangle))), set()).add(int(tag))
    return {face: frozenset(tags) for face, tags in tags_by_face.items()}


def selected_tetrahedra(mesh: meshio.Mesh, selected_volume_tags: Iterable[int]) -> np.ndarray:
    """Return the tetrahedra (4 or 10 node columns) of the selected physical volume tags."""

    selected_tags = tuple(int(tag) for tag in selected_volume_tags)
    physical_blocks = mesh.cell_data.get("gmsh:physical")
    if physical_blocks is None or len(physical_blocks) != len(mesh.cells):
        raise ValueError("FEM mesh tetrahedra do not contain gmsh:physical volume tags.")
    selected: list[np.ndarray] = []
    for block, raw_tags in zip(mesh.cells, physical_blocks, strict=True):
        if block.type not in _TETRAHEDRON_TYPES:
            continue
        cells = np.asarray(block.data, dtype=np.int64)
        tags = np.asarray(raw_tags, dtype=np.int64)
        if tags.shape != (cells.shape[0],):
            raise ValueError("FEM mesh physical-volume tags do not align with its tetrahedra.")
        mask = np.isin(tags, selected_tags)
        if np.any(mask):
            selected.append(cells[mask])
    if not selected:
        return np.empty((0, 4), dtype=np.int64)
    widths = {cells.shape[1] for cells in selected}
    if len(widths) != 1:
        raise ValueError("FEM mesh mixes first- and second-order tetrahedra.")
    return np.vstack(selected)


def mean_tetrahedron_edge_length(points: np.ndarray, tetrahedra: np.ndarray) -> float:
    """Return the mean corner-to-corner edge length of tetrahedra, repeated edges included."""

    vertices = np.asarray(points, dtype=float)[np.asarray(tetrahedra, dtype=np.int64)[:, :4]]
    pairs = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    return float(np.mean([np.linalg.norm(vertices[:, b] - vertices[:, a], axis=1) for a, b in pairs]))


def _physical_blocks(mesh: meshio.Mesh) -> list:
    physical_blocks = mesh.cell_data.get("gmsh:physical")
    if physical_blocks is None or len(physical_blocks) != len(mesh.cells):
        raise ValueError("FEM mesh elements do not contain aligned gmsh:physical tags.")
    return physical_blocks


__all__ = [
    "mean_tetrahedron_edge_length",
    "selected_tetrahedra",
    "selected_volume_exterior_faces",
    "selected_volume_surface_tags",
    "triangle_tags_by_face",
]
