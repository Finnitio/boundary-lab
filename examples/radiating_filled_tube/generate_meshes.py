"""Write the meshes of the radiating filled tube example (lengths in mm; the project scales by 0.001).

A 20 mm x 20 mm x 50 mm tube along +z is completely filled with a porous material. A piston
drives the z = 0 end and the z = 50 mm end opens into free space through an FEM-BEM interface.

``tube.msh`` (FEM volume): ``Volume``, ``Piston`` (z = 0), ``Opening`` (z = 50 mm), ``Walls``.
``exterior.msh`` (BEM surface): the tube's outer surface with outward normals, ``Opening`` and
the rigid ``Body`` (the outside of the walls and of the piston end).

The cross-section is the unit square split into six triangles around two interior vertices of
degree 5. That opening triangulation is not three-colourable, so the projected interface flux
has full column rank (BEAT Engine ``docs/Projected interface flux.md``). Each 1.25 mm slab is a
layer of prisms split into three tetrahedra by vertex order, so neighbouring prisms conform.

Regenerate: python generate_meshes.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import gmsh
import meshio
import numpy as np

WIDTH_MM = 20.0
LENGTH_MM = 50.0
SLABS = 40
SECTION_POINTS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.525, 0.7), (0.525, 0.2875))
SECTION_TRIANGLES = ((2, 1, 4), (3, 2, 4), (4, 0, 3), (1, 0, 5), (5, 0, 4), (4, 1, 5))
VOLUME, PISTON, OPENING, WALLS = 1, 2, 3, 4
BODY, BEM_OPENING = 1, 2


def tube_meshes() -> tuple[meshio.Mesh, meshio.Mesh]:
    count = len(SECTION_POINTS)
    points = np.array(
        [(WIDTH_MM * x, WIDTH_MM * y, slab * LENGTH_MM / SLABS) for slab in range(SLABS + 1) for x, y in SECTION_POINTS]
    )
    tetrahedra = []
    for slab in range(SLABS):
        for triangle in SECTION_TRIANGLES:
            a, b, c = (vertex + count * slab for vertex in sorted(triangle))
            a1, b1, c1 = a + count, b + count, c + count
            tetrahedra.extend(((a, b, c, c1), (a, b, b1, c1), (a, a1, b1, c1)))
    tetrahedra = np.array([_positive(points, tet) for tet in tetrahedra])

    faces = Counter(tuple(sorted(face)) for tet in tetrahedra for face in _faces(tet))
    centre = np.array([WIDTH_MM / 2, WIDTH_MM / 2, LENGTH_MM / 2])
    exterior = sorted(_outward(points, face, centre) for face, n in faces.items() if n == 1)
    tags = np.array([_fem_tag(points, face) for face in exterior])
    triangles = np.array(exterior)
    fem = meshio.Mesh(
        points,
        [("triangle", triangles), ("tetra", tetrahedra)],
        cell_data={
            "gmsh:physical": [tags, np.full(len(tetrahedra), VOLUME)],
            "gmsh:geometrical": [tags, np.full(len(tetrahedra), VOLUME)],
        },
        field_data={
            "Volume": np.array([VOLUME, 3]),
            "Piston": np.array([PISTON, 2]),
            "Opening": np.array([OPENING, 2]),
            "Walls": np.array([WALLS, 2]),
        },
    )

    # The BEM surface keeps only the tube's surface vertices.
    surface = np.unique(triangles)
    renumber = np.full(len(points), -1)
    renumber[surface] = np.arange(len(surface))
    bem_tags = np.where(tags == OPENING, BEM_OPENING, BODY)
    bem = meshio.Mesh(
        points[surface],
        [("triangle", renumber[triangles])],
        cell_data={"gmsh:physical": [bem_tags], "gmsh:geometrical": [bem_tags]},
        field_data={"Body": np.array([BODY, 2]), "Opening": np.array([BEM_OPENING, 2])},
    )
    return fem, bem


def _faces(tet):
    a, b, c, d = tet
    return ((a, b, c), (a, b, d), (a, c, d), (b, c, d))


def _positive(points, tet):
    a, b, c, d = (points[vertex] for vertex in tet)
    return tet if np.dot(np.cross(b - a, c - a), d - a) > 0 else (tet[0], tet[2], tet[1], tet[3])


def _outward(points, face, centre):
    a, b, c = (points[vertex] for vertex in face)
    return face if np.dot(np.cross(b - a, c - a), (a + b + c) / 3 - centre) > 0 else (face[0], face[2], face[1])


def _fem_tag(points, face):
    z = points[list(face), 2]
    return PISTON if np.all(z == 0.0) else OPENING if np.all(z == LENGTH_MM) else WALLS


def write_gmsh41(path: Path, mesh: meshio.Mesh) -> None:
    """Write an ASCII Gmsh 4.1 file (BEAT Engine reads FEM volume meshes as 4.1, BEM surfaces as 2.2).

    Each physical group is one discrete entity with the same tag; all nodes sit on the first
    entity of the highest dimension.
    """

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(path.stem)
        names = {(int(dim), int(tag)): name for name, (tag, dim) in mesh.field_data.items()}
        for dim, tag in sorted(names, key=lambda key: (-key[0], key[1])):
            gmsh.model.addDiscreteEntity(dim, tag)
        node_entity = max(names, key=lambda key: (key[0], -key[1]))
        gmsh.model.mesh.addNodes(*node_entity, np.arange(1, len(mesh.points) + 1), mesh.points.ravel())
        element_types = {"triangle": (2, 2), "tetra": (3, 4)}
        next_element = 1
        for block, tags in zip(mesh.cells, mesh.cell_data["gmsh:physical"]):
            dim, element_type = element_types[block.type]
            for tag in np.unique(tags):
                connectivity = block.data[tags == tag]
                elements = np.arange(next_element, next_element + len(connectivity))
                next_element += len(connectivity)
                gmsh.model.mesh.addElementsByType(int(tag), element_type, elements, (connectivity + 1).ravel())
        for (dim, tag), name in names.items():
            gmsh.model.addPhysicalGroup(dim, [tag], tag, name)
        gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def main() -> None:
    here = Path(__file__).resolve().parent
    fem, bem = tube_meshes()
    write_gmsh41(here / "tube.msh", fem)
    meshio.write(here / "exterior.msh", bem, file_format="gmsh22", binary=False)


if __name__ == "__main__":
    main()
