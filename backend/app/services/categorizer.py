"""Map loops to sampleEngine categories based on stem origin and audio characteristics."""

from statistics import median

from .loop_chopper import Loop

VALID_CATEGORIES = frozenset({
    "foundation", "groove", "bass", "harmonic_bed", "hook", "texture", "accent",
})


def categorize_loops(loops_by_stem: dict[str, list[Loop]]) -> list[Loop]:
    """Assign .category to each loop based on stem type and audio features.

    Stem keys should be: drums, bass, vocals, other.
    """
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
    max_per_category: int = 3,
) -> list[dict]:
    """Pick top N loops per category by energy.

    Returns list of dicts matching the .perf.json sample_tracks contract.
    """
    by_category: dict[str, list[Loop]] = {}
    for loop in loops:
        by_category.setdefault(loop.category, []).append(loop)

    selected_files: set[str] = set()
    for cat_loops in by_category.values():
        cat_loops.sort(key=lambda l: l.energy, reverse=True)
        for loop in cat_loops[:max_per_category]:
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
            "selected": loop.file in selected_files,
        }
        for loop in loops
    ]
