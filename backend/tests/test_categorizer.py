"""Unit tests for loop categorization and auto-selection (the taste layer).

Pure logic over Loop dataclasses — no audio, no network. Pins the documented
category rules (groove/foundation/accent/bass/hook/harmonic_bed/texture) and
the "top N per category per section by energy" auto-selection.
"""

from app.services.categorizer import auto_select, categorize_loops
from app.services.loop_chopper import Loop


def _loop(**overrides) -> Loop:
    base = dict(
        file="x.wav",
        start_sec=0.0,
        end_sec=8.0,
        duration_sec=8.0,
        bars=4,
        energy=0.1,
        category="",
        mode="loop",
        volume=-12.0,
        section="verse",
    )
    base.update(overrides)
    return Loop(**base)


# ---------------------------------------------------------------------------
# categorize_loops — per-stem rules
# ---------------------------------------------------------------------------

def test_drums_oneshot_is_accent():
    loops = categorize_loops({"drums": [_loop(mode="oneshot", bars=1, energy=0.2)]})
    assert loops[0].category == "accent"


def test_drums_split_groove_vs_foundation_by_median_energy():
    # median of [0.1, 0.3] = 0.2; >=median -> groove, below -> foundation.
    low = _loop(file="lo.wav", mode="loop", bars=4, energy=0.1)
    high = _loop(file="hi.wav", mode="loop", bars=4, energy=0.3)
    categorize_loops({"drums": [low, high]})
    assert high.category == "groove"
    assert low.category == "foundation"


def test_bass_is_always_bass():
    loops = categorize_loops({"bass": [_loop(energy=0.01), _loop(energy=0.9)]})
    assert all(l.category == "bass" for l in loops)


def test_vocals_long_phrase_is_hook():
    loops = categorize_loops({"vocals": [_loop(bars=4, duration_sec=8.0)]})
    assert loops[0].category == "hook"
    assert loops[0].mode == "loop"


def test_vocals_short_phrase_is_accent_oneshot():
    # bars<=2 and duration<=3.0 -> accent, forced to oneshot.
    loops = categorize_loops({"vocals": [_loop(bars=1, duration_sec=2.0, mode="loop")]})
    assert loops[0].category == "accent"
    assert loops[0].mode == "oneshot"


def test_vocals_long_duration_even_if_few_bars_is_hook():
    loops = categorize_loops({"vocals": [_loop(bars=1, duration_sec=5.0)]})
    assert loops[0].category == "hook"


def test_other_split_harmonic_bed_vs_texture_by_median():
    low = _loop(file="lo.wav", energy=0.1)
    high = _loop(file="hi.wav", energy=0.3)
    categorize_loops({"other": [low, high]})
    assert high.category == "harmonic_bed"
    assert low.category == "texture"


def test_empty_stem_list_skipped():
    assert categorize_loops({"drums": []}) == []


# ---------------------------------------------------------------------------
# auto_select — top N per (category, section) by energy
# ---------------------------------------------------------------------------

def test_auto_select_marks_top_n_per_category_section():
    loops = [
        _loop(file="g1.wav", category="groove", section="verse", energy=0.9),
        _loop(file="g2.wav", category="groove", section="verse", energy=0.5),
        _loop(file="g3.wav", category="groove", section="verse", energy=0.1),
    ]
    result = auto_select(loops, max_per_category_per_section=2)
    by_file = {r["file"]: r["selected"] for r in result}
    assert by_file["g1.wav"] is True
    assert by_file["g2.wav"] is True
    assert by_file["g3.wav"] is False   # third-highest energy, dropped


def test_auto_select_separates_by_section():
    loops = [
        _loop(file="v.wav", category="groove", section="verse", energy=0.2),
        _loop(file="c.wav", category="groove", section="chorus", energy=0.2),
    ]
    result = auto_select(loops, max_per_category_per_section=1)
    # Different sections -> each is top-1 of its own group -> both selected.
    assert all(r["selected"] for r in result)


def test_auto_select_returns_full_contract_shape():
    loops = [_loop(file="a.wav", category="bass", section="verse", energy=0.4)]
    result = auto_select(loops)
    row = result[0]
    for key in ("file", "category", "mode", "volume", "bars", "duration_sec", "energy", "section", "selected"):
        assert key in row


def test_auto_select_returns_every_loop():
    loops = [_loop(file=f"{i}.wav", category="groove", section="verse", energy=i / 10) for i in range(5)]
    result = auto_select(loops, max_per_category_per_section=2)
    assert len(result) == 5
    assert sum(1 for r in result if r["selected"]) == 2
