# Applying fleet changes in GAMA

Run me initializes its controls from `configs/gama/environment.json`. It does
not automatically load Python's `research.json`. Collect training data loads
its registered calibration profile and intentionally replaces those GUI inputs.

After changing a control marked **restart required**, use **Reloads the current
experiment (Ctrl+R)**, the second circular-arrow toolbar button. Reverting/resetting
the simulation is a different operation: it can restore the previous population
while retaining a changed parameter value. The population integrity assertion
then rejects the inconsistent state. Do not continue that simulation or weaken
the assertion; reload the experiment.

Desktop validation on 2026-10-24 confirmed the default controls 3000/1000/700
and 4700 entries in `initial_fleet.json`. A GUI-only fixture changed cars to823;
after Ctrl+R its exported configuration and actual initial fleet were both
823/1000/700 (2523 vehicles). Production JSON files were not changed.

Configured fleet, instantiated agents, currently moving/charging agents, and
icons distinguishable on screen have different counts. Computer draws all
three vehicle species, but many icons overlap at the full-city zoom. Use the
population monitors and exported initial fleet to check counts. Preserve the
map, sprites and layers when changing parameters.

The first GUI test used a 3GiB heap and reported low memory. The completed
desktop reload test used 8GiB in an isolated workspace. GUI trials are partial
development episodes and must not be imported as calibration or research runs.
