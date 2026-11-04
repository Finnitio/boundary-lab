// Filled tube: a 20 mm x 20 mm x 100 mm tube along +z, completely filled with a porous
// material. A piston drives the z = 0 end and the z = 100 mm end is closed rigidly.
// Lengths in mm (the project scales by 0.001). A structured mesh of 1.25 mm slabs keeps
// the plane-wave error small enough to compare the input impedance with -j Zc cot(kc L).
// Regenerate: gmsh filled_tube.geo -3 -o filled_tube.msh
SetFactory("Built-in");
width = 20;
length = 100;
across = 2;
slabs = 80;

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
tube[] = Extrude {0, 0, length} { Surface{1}; Layers{slabs}; };
// tube[0] = end face, tube[1] = volume, tube[2..5] = side walls.

Physical Volume("Tube") = {tube[1]};
Physical Surface("Piston") = {1};
Physical Surface("End") = {tube[0]};
Physical Surface("Walls") = {tube[2], tube[3], tube[4], tube[5]};
