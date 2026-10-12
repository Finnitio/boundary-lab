**Idea: Model Tree layout for the GUI (COMSOL-style)**

Hi all, hi JW — another idea I'd like to float before opening any issues, this time about the GUI.

As features get added, the GUI is getting harder to navigate. Editing a component currently takes about 7 clicks and 2 stacked dialogs (System → Components → select → Edit → change → OK → OK), and the dialogs cover the mesh preview, so you can't see which surface you're editing. Each new feature adds another button and another dialog.

Clickable prototype (example data from `MultiAth+Mesh_3WayIntegrated`, curves are illustrative): https://claude.ai/artifact/LvW144hTQdnwUQd4UWM6Lk

**1. Three panes: Model Tree | Settings | Graphics**
- The tree shows the whole project in workflow order: Geometry → Meshes → System (Regions, Boundaries, Interfaces, Components) → Channels → Solve → Results.
- It mirrors the `.blab.json` structure, so the file format doesn't change.
- Selecting a node shows its settings in the middle pane. Right-click or "+" adds children (Add Component, Add Plot, Import .msh…).

**2. Graphics that follow the selection**
- Select a component and its moving surfaces are highlighted in 3D with a motion-direction arrow.
- Select a design or mesh and the others are ghosted. Select a channel and its on-axis response is emphasized.

**3. Live edits with Undo/Redo**
- No OK/Cancel/Apply: changes apply immediately and Ctrl+Z reverts them. Undo would be new work and is the prerequisite for this.

**4. State visible in the tree**
- Interfaces is greyed out until both bounded and unbounded regions exist, and invalid components are disabled with a reason.
- Solve/Results show *out of date* after model changes, but not after channel edits, since those only resynthesize.

**5. Plot Groups under Results**
- Each group holds any number of plots side by side. A default "Overview" group reproduces today's dock layout.

**What stays the same:** project file format, solver backend, settings in Preferences, plot interactions (crosshair, compare, PNG export), and keyboard shortcuts. Generate/Solve/Stop stay global in the toolbar.

**Possible migration path**
1. Add the tree and settings pages hosting the existing dialog contents, without OK/Cancel.
2. Add the selection-aware graphics, reusing the mesh preview's surface picking.
3. Replace the fixed docks with Plot Groups and add the undo stack.

**Questions for JW**
- Would you accept a layout change of this size upstream, done incrementally as above?
- Is live editing + undo acceptable, or would you prefer to keep explicit Apply?
- Any thoughts on the tree structure, or parts of the current GUI you'd want kept as they are?

I'd be happy to do the implementation work if this fits.
