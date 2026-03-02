"""Categorize loops by musical role and select the best per section."""

from statistics import median

from .loop_chopper import Loop


def categorize_loops(loops_by_stem: dict[str, list[Loop]]) -> list[Loop]:
    """Assign .category to each loop based on stem type and audio features."""
    all_loops: list[Loop] = []

    for stem, loops in loops_by_stem.items():
        if not loops:
            continue

        energies = [l.energy for l in loops]
        med_energy = median(energies) if energies else 0.0

        for loop in loops:
            if stem == "drums":
                if loop.mode == "oneshot" or loop.bars <= 1:
                    loop.category = "accent"
                elif loop.energy >= med_energy:
                    loop.category = "groove"
                else:
                    loop.category = "foundation"

            elif stem == "bass":
                loop.category = "bass"

            elif stem == "vocals":
                if loop.bars > 2 or loop.duration_sec > 3.0:
                    loop.category = "hook"
                else:
                    loop.category = "accent"
                    loop.mode = "oneshot"

            else:  # other / melody / instruments
                if loop.energy >= med_energy:
                    loop.category = "harmonic_bed"
                else:
                    loop.category = "texture"

            all_loops.append(loop)

    return all_loops


def auto_select(
    loops: list[Loop],
    max_per_category_per_section: int = 2,
) -> list[dict]:
    """Pick top N loops per category per song section by energy.

    Returns list of dicts matching the .perf.json sample_tracks contract.
    """
    # Group by (category, section)
    groups: dict[tuple[str, str], list[Loop]] = {}
    for loop in loops:
        key = (loop.category, loop.section)
        groups.setdefault(key, []).append(loop)

    selected_files: set[str] = set()
    for group_loops in groups.values():
        group_loops.sort(key=lambda l: l.energy, reverse=True)
        for loop in group_loops[:max_per_category_per_section]:
            selected_files.add(loop.file)

    return [
        {
            "file": loop.file,
            "category": loop.category,
            "mode": loop.mode,
            "volume": loop.volume,
            "bars": loop.bars,
            "duration_sec": loop.duration_sec,
            "energy": loop.energy,
            "section": loop.section,
            "selected": loop.file in selected_files,
        }
        for loop in loops
    ]
