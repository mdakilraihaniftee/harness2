# Offline fixtures

The suite reuses the versioned deterministic fixtures in `research_pilots.fixtures` and
derives temporary per-task trees at runtime. Hidden utility records are written only to the
machine-readable results directory; they are never placed in composer-visible workspaces.
