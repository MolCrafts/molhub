# Properties and selection

MolVis owns the live structure and trajectory. MolPlot owns the property map. MolHub links them by the
stable frame index: clicking a point seeks the viewer and viewer trajectory events update the active
point. The selected frame is also rendered as text, so state is not conveyed only by color.

For 3BPA the honest first map is frame index against energy. The viewer also reports live selected atom
counts. Environment-level maps require an explicit derived property target and stable atom/environment
identifiers; filters must never renumber frames.
