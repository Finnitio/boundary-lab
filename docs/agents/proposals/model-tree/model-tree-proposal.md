# Proposal: Model Tree layout for the Boundary Lab GUI

**Clickable prototype:** https://claude.ai/artifact/LvW144hTQdnwUQd4UWM6Lk
(example data from `examples/MultiAth+Mesh_3WayIntegrated`; curves are illustrative, not solve results)

## Problem

The GUI works, but it is already getting hard to navigate. Editing a component today takes
**7 clicks and 2 stacked modal windows**: System → Components tab → select row → Edit →
change value → OK → OK. While those windows are open, the mesh preview is covered, so you
can't see which surface you're editing. Every new feature adds another button to the command
strip and another dialog, so this will get worse as Boundary Lab grows.

## Proposal

A three-pane layout inspired by COMSOL's Model Builder:

| Model Tree (left) | Settings (middle) | Graphics (right) |
|---|---|---|
| Whole project in workflow order | Settings of the selected node, applied live | Follows the selection |

**Model Tree** (mirrors the `.blab.json` structure; the file format does not change):

```
Geometry      → Ath designs
Meshes        → generated + imported meshes, symmetry
System        → Regions, Boundaries, Interfaces, Components → each component
Channels      → each channel
Solve         → frequency range, Compute
Results       → Plot Groups → Plots
```

Right-clicking a node (or the "+" button) adds children: Add Component, Add Plot, Import .msh, and so on.

## Key behaviours

- **Selection-aware graphics:** select a component and its moving surfaces are highlighted in
  3D, with a motion-direction arrow. Select a design or mesh and the others are ghosted. Select a
  channel and the on-axis response is shown with that channel emphasized.
- **Live edits + Undo/Redo:** no OK/Cancel/Apply. Changes apply immediately and Ctrl+Z reverts them.
  *Undo is new work and is the prerequisite for live editing.*
- **Plot Groups:** under Results, each group holds any number of plots, shown side by side. The
  default "Overview" group reproduces today's dock layout, so the multi-plot view isn't lost.
- **State is visible in the tree:** Interfaces is greyed out until both bounded and unbounded regions
  exist. Electrodynamic components are disabled with a reason in exterior-only systems. Solve and
  Results show *out of date* after a model change, but not after channel changes, because those only
  resynthesize the results.
- **Generate/Solve/Stop** stay global (toolbar, F7/F5/Shift+F5) and also appear as buttons on the
  matching nodes.

## What stays the same

- Project file format
- Solver backend and app settings stay in **Edit › Preferences**; the Solve node only displays them.
- Plot interactions (crosshair, right-click compare, PNG export)
- Keyboard shortcuts

## Possible migration path

1. Add the tree and stacked settings pages that host the existing dialog contents (Regions,
   Boundaries, Interfaces, Components and Channels tables) without OK/Cancel.
2. Add the graphics area that follows the selection, reusing the mesh preview's surface picking for
   highlights.
3. Replace the fixed docks with Plot Groups and add an undo stack.

Feedback welcome, especially on the tree structure and on whether live editing plus undo is
acceptable.
