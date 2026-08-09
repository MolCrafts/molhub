# Opening an artifact

Compatible file rows on an artifact detail page show **Inspect**. Compatibility requires declared
format/media type, an HTTP source, a MolVis reader, and a bounded direct-download size. Filename suffixes
do not enable the button.

The Inspector URL preserves coordinate, role, frame, x/y axes, and color. Copying the URL restores the
same scientific view without embedding a temporary source URL. Changing role disconnects the old
MolVis element, which aborts its fetch and destroys its scene.

Unsupported roles remain downloadable. Large or archive formats require a derived record rather than
a button that predictably fails.
