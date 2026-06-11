"""Concept-graph extraction package.

Shared constants live here so lightweight consumers (e.g. the seed script)
can import them without pulling in the full pipeline module.
"""
from __future__ import annotations

# Concepts created by the seed script carry this origin. The extraction
# pipeline exempts them from orphan pruning and never overwrites their
# curated summary (the /graph API already hides concepts with zero visible
# sources, so orphaned seed concepts disappear from view without being
# destroyed).
SEED_ORIGIN = "seed"
