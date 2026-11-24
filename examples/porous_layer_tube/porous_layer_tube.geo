// Air tube with a porous layer: a 20 mm x 20 mm x 100 mm tube along +z. A piston drives the
// z = 0 end, air fills 0..50 mm, a rigid-backed porous layer fills 50..100 mm and the
// z = 100 mm end is closed rigidly. Both volumes share the z = 50 mm face, which belongs to
// no physical surface group: it is a region seam, so sound passes from the air into the
// layer without a boundary or interface. Lengths in mm (the project scales by 0.001).
// A structured mesh of 1.25 mm slabs keeps the plane-wave error small enough to compare
// with the transfer-matrix solution. Regenerate: gmsh porous_layer_tube.geo -3 -o porous_layer_tube.msh
SetFactory("Built-in");
width = 20;
air_length = 50;
layer_length = 50;
across = 2;
slab = 1.25;

Point(1) = {0, 0, 0};
Point(2) = {width, 0, 0};
Point(3) = {width, width, 0};
Point(4) = {0, width, 0};
Line(1) = {1, 2};
Line(2) = {2, 3};
Line(3) = {3, 4};
Line(4) = {4, 1};
Curve Loop(1) = {1, 2, 3, 4};
Plane Surface(1) = {1};
Transfinite Curve {1, 2, 3, 4} = across + 1;
Transfinite Surface {1};
air[] = Extrude {0, 0, air_length} { Surface{1}; Layers{air_length / slab}; };
// air[0] = seam face, air[1] = volume, air[2..5] = side walls.
layer[] = Extrude {0, 0, layer_length} { Surface{air[0]}; Layers{layer_length / slab}; };
// layer[0] = rigid end, layer[1] = volume, layer[2..5] = side walls.

Physical Volume("Air") = {air[1]};
Physical Volume("Layer") = {layer[1]};
Physical Surface("Piston") = {1};
Physical Surface("Air walls") = {air[2], air[3], air[4], air[5]};
Physical Surface("Layer walls") = {layer[2], layer[3], layer[4], layer[5]};
Physical Surface("End") = {layer[0]};
