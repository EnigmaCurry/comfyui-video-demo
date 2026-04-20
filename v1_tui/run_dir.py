"""Shared helper for computing the run directory path."""

import os
import re
import glob


def find_run_dir(output_dir, seed):
    """Find an existing run directory for a seed, or return the default path.

    Looks for output/{seed}-*/ first (themed), falls back to output/{seed}/.
    """
    pattern = os.path.join(output_dir, f"{seed}-*")
    matches = sorted(glob.glob(pattern))
    # Filter to directories that start with the exact seed prefix
    matches = [m for m in matches if os.path.isdir(m)
               and os.path.basename(m).split("-", 1)[0] == str(seed)]
    if matches:
        return matches[0]
    # Fall back to bare seed directory
    bare = os.path.join(output_dir, str(seed))
    if os.path.isdir(bare):
        return bare
    return None


def make_run_dir(output_dir, seed, theme=None):
    """Create and return the run directory path.

    If theme is provided: output/{seed}-{theme-slug}/
    Otherwise: output/{seed}/
    """
    # Check if one already exists for this seed
    existing = find_run_dir(output_dir, seed)
    if existing:
        return existing

    if theme:
        slug = re.sub(r'[^a-z0-9]+', '-', theme.lower()).strip('-')
        # Truncate slug to keep directory names reasonable
        if len(slug) > 60:
            slug = slug[:60].rstrip('-')
        run_dir = os.path.join(output_dir, f"{seed}-{slug}")
    else:
        run_dir = os.path.join(output_dir, str(seed))

    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def get_run_dir(output_dir, seed):
    """Get the run directory for a seed, or error if not found."""
    found = find_run_dir(output_dir, seed)
    if found:
        return found
    # Fall back to bare seed (will be created if needed)
    return os.path.join(output_dir, str(seed))
