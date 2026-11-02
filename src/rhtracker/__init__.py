"""rhtracker — layered Robinhood portfolio tracker package.

Three layers with a strict downward-only dependency rule:

  scripts / cli   ->  services  ->  library (model, sources, storage,
                                             reconstruct, reporting)

``model`` sits at the bottom as the shared vocabulary; everything may depend
on it and it depends on nothing else in the package.

Run from source (no pip install required)::

    python -m rhtracker <command>

with ``src/`` on the path.
"""
