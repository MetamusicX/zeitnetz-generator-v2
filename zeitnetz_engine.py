"""
Zeitnetz Generator v2 — Extended engine for browser execution via Pyodide.

All computation stages (1-5), validation, discovery, discovery-by-families,
custom time signatures, and pure-Python MusicXML export (no music21 dependency).
Runs entirely client-side.
"""

import random
import json
import math
from fractions import Fraction
from xml.etree.ElementTree import Element, SubElement, tostring

# ===================================================================
# CONSTANTS
# ===================================================================

FAMILY_ROW_ORDER = [7, 8, 9, 10, 11, 0, 1, 2, 3, 4, 5, 6]
END_PITCH_ROW_ORDER = [6, 5, 4, 3, 2, 1, 0, 11, 10, 9, 8, 7]
CONTROL_ROW_INDEX = 10
BAR = 12
MAX_CYCLES = 20

DEFAULT_TS_SEQ = [
    7, 6, 6, 5, 5, 5, 4, 4, 4, 4, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4,
    5, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    6, 6, 6, 6, 6, 6, 5, 5, 5, 5, 5, 4, 4, 4, 4, 3, 3, 3, 2, 2, 1,
]

# ===================================================================
# PITCH UTILITIES
# ===================================================================

GERMAN_TO_PC = {
    "c": 0, "cis": 1, "d": 2, "dis": 3, "e": 4, "f": 5,
    "fis": 6, "g": 7, "gis": 8, "a": 9, "ais": 10, "b": 10,
    "h": 11, "his": 0, "ces": 11, "des": 1, "es": 3, "ges": 6, "as": 8,
}

PC_TO_GERMAN = {
    0: "c", 1: "cis", 2: "d", 3: "dis", 4: "e", 5: "f",
    6: "fis", 7: "g", 8: "gis", 9: "a", 10: "ais", 11: "h",
}

# MusicXML pitch data: (step, alter, octave)
PC_TO_XML_PITCH = {
    0: ("C", 0, 4), 1: ("C", 1, 4), 2: ("D", 0, 4), 3: ("D", 1, 4),
    4: ("E", 0, 4), 5: ("F", 0, 4), 6: ("F", 1, 4), 7: ("G", 0, 4),
    8: ("G", 1, 4), 9: ("A", 0, 4), 10: ("A", 1, 4), 11: ("B", 0, 4),
}


def pc_name(pc):
    return PC_TO_GERMAN[pc % 12]


def parse_pitch_input(s):
    s = s.replace(",", " ")
    tokens = s.strip().split()
    if len(tokens) != 12:
        raise ValueError(f"Pitch row must have 12 values, got {len(tokens)}")
    result = []
    for t in tokens:
        try:
            v = int(t)
            if not 0 <= v <= 11:
                raise ValueError(f"PC {v} out of range 0-11")
            result.append(v)
        except ValueError:
            tl = t.lower()
            if tl in GERMAN_TO_PC:
                result.append(GERMAN_TO_PC[tl])
            else:
                raise ValueError(f"Unknown pitch name: '{t}'")
    if set(result) != set(range(12)):
        raise ValueError("Pitch row must contain each class 0-11 exactly once")
    return result


def parse_int_list(s, expected, name):
    s = s.replace(",", " ")
    tokens = s.strip().split()
    if len(tokens) != expected:
        raise ValueError(f"{name} must have {expected} values, got {len(tokens)}")
    return [int(t) for t in tokens]


# ===================================================================
# TIME SIGNATURES
# ===================================================================

# divisions = 24 per quarter note
# Each type: (ts_beats, ts_beat_type, unit_dur_divs, is_tuplet,
#             written_type, tup_actual, tup_normal, full_group_type)
TS_DEFS = {
    1: {"ts": (3, 8),  "unit": 3,  "tup": False, "wtype": "32nd"},
    2: {"ts": (4, 8),  "unit": 4,  "tup": True,  "wtype": "16th",
        "ta": 3, "tn": 2, "group_type": "eighth", "group_dur": 12},
    3: {"ts": (3, 4),  "unit": 6,  "tup": False, "wtype": "16th"},
    4: {"ts": (4, 4),  "unit": 8,  "tup": True,  "wtype": "eighth",
        "ta": 3, "tn": 2, "group_type": "quarter", "group_dur": 24},
    5: {"ts": (3, 2),  "unit": 12, "tup": False, "wtype": "eighth"},
    6: {"ts": (4, 2),  "unit": 16, "tup": True,  "wtype": "quarter",
        "ta": 3, "tn": 2, "group_type": "half", "group_dur": 48},
    7: {"ts": (12, 4), "unit": 24, "tup": False, "wtype": "quarter"},
}

# Duration-to-type mapping for rests (non-tuplet)
DUR_TO_TYPE = {
    3: ("32nd", False),
    6: ("16th", False),
    9: ("16th", True),      # dotted
    12: ("eighth", False),
    18: ("eighth", True),
    24: ("quarter", False),
    36: ("quarter", True),
    48: ("half", False),
    72: ("half", True),
    96: ("whole", False),
    144: ("whole", True),
    288: ("breve", False),
}


def decompose_duration(dur):
    """Split a duration into a list of (dur, type, dotted) tuples."""
    result = []
    remaining = dur
    for d in sorted(DUR_TO_TYPE.keys(), reverse=True):
        while remaining >= d:
            typ, dotted = DUR_TO_TYPE[d]
            result.append((d, typ, dotted))
            remaining -= d
    if remaining > 0:
        # Fallback: use smallest unit
        result.append((remaining, "32nd", False))
    return result


def get_ts_for_bar(bar_index, ts_sequence):
    return ts_sequence[bar_index % len(ts_sequence)]


def generate_auto_ts_sequence(n_bars):
    if n_bars <= 0:
        return []
    cycle = []
    for t in range(7, 0, -1):
        if t == 7: count = 1
        elif t == 1: count = 14
        else: count = 8 - t
        cycle.extend([t] * count)
    for t in range(2, 8):
        count = 14 if t == 7 else 7
        cycle.extend([t] * count)
    for t in range(6, 0, -1):
        cycle.extend([t] * t)
    return cycle


def parse_ts_sequence(s):
    s = s.replace(",", " ")
    tokens = s.strip().split()
    if not tokens:
        raise ValueError("Time signature sequence cannot be empty")
    result = []
    for t in tokens:
        v = int(t)
        if not 1 <= v <= 7:
            raise ValueError(f"TS type {v} out of range 1-7")
        result.append(v)
    return result


# ===================================================================
# CUSTOM TIME SIGNATURE SUPPORT
# ===================================================================

# Map from divisions-per-note to MusicXML type name
# Using 24 divisions per quarter note:
#   whole=96, half=48, quarter=24, eighth=12, 16th=6, 32nd=3
DIVS_TO_NOTE_TYPE = {
    192: "breve",
    96: "whole",
    48: "half",
    24: "quarter",
    12: "eighth",
    6: "16th",
    3: "32nd",
}

# Standard subdivisions per beat (powers of 2)
STANDARD_SUBDIVISIONS = [1, 2, 4, 8]


def _beat_duration_divs(beat_type):
    """Return the duration of one beat in divisions (24 per quarter)."""
    # beat_type: 1=whole, 2=half, 4=quarter, 8=eighth, 16=sixteenth
    return 96 // beat_type


def _closest_standard(n):
    """Find closest power-of-2 standard subdivision count."""
    best = 1
    best_dist = abs(n - 1)
    for s in STANDARD_SUBDIVISIONS:
        d = abs(n - s)
        if d < best_dist:
            best = s
            best_dist = d
    return best


def _note_type_for_duration(dur_divs):
    """Find the best MusicXML note type for a given duration in divisions."""
    if dur_divs in DIVS_TO_NOTE_TYPE:
        return DIVS_TO_NOTE_TYPE[dur_divs], False
    # Try dotted
    base = dur_divs * 2 // 3
    if base in DIVS_TO_NOTE_TYPE and base * 3 // 2 == dur_divs:
        return DIVS_TO_NOTE_TYPE[base], True
    # Find closest smaller standard duration
    for d in sorted(DIVS_TO_NOTE_TYPE.keys(), reverse=True):
        if d <= dur_divs:
            return DIVS_TO_NOTE_TYPE[d], False
    return "32nd", False


def _distribute_positions(n_positions, n_beats):
    """Distribute n_positions across n_beats as evenly as possible.
    Returns a list of group sizes, e.g. distribute(12, 5) -> [3, 3, 2, 2, 2]
    or [2, 2, 3, 2, 3] depending on strategy. We put larger groups first.
    """
    base = n_positions // n_beats
    extra = n_positions % n_beats
    groups = []
    for i in range(n_beats):
        if i < extra:
            groups.append(base + 1)
        else:
            groups.append(base)
    return groups


def build_custom_ts_def(beats, beat_type):
    """Build a TS_DEFS-compatible dict for a custom time signature.

    The time signature has `beats` beats of `beat_type` (e.g., 7/8 = 7 beats of 8th).
    We must fit exactly 12 grid positions into this bar.

    Returns a dict with keys matching TS_DEFS entries, plus extra keys
    for beat-by-beat rendering if beats are uneven.
    """
    beat_dur = _beat_duration_divs(beat_type)  # duration of one beat in divs
    total_dur = beats * beat_dur               # total bar duration in divs

    # Distribute 12 positions across beats
    groups = _distribute_positions(12, beats)

    # Check if all groups are the same size (uniform case)
    all_same = len(set(groups)) == 1

    if all_same:
        # Uniform distribution: simpler case
        positions_per_beat = groups[0]
        unit_dur = beat_dur // positions_per_beat
        remainder = beat_dur % positions_per_beat

        if remainder == 0 and unit_dur in DIVS_TO_NOTE_TYPE:
            # Clean division, no tuplet needed
            return {
                "ts": (beats, beat_type),
                "unit": unit_dur,
                "tup": False,
                "wtype": DIVS_TO_NOTE_TYPE[unit_dur],
                "custom": False,
            }
        else:
            # Need tuplet: positions_per_beat notes in the space of
            # the closest standard subdivision
            normal_count = _closest_standard(positions_per_beat)
            normal_dur = beat_dur // normal_count if normal_count > 0 else beat_dur
            note_type, _ = _note_type_for_duration(normal_dur)
            actual_unit = beat_dur // positions_per_beat  # may not be integer in divs

            # For tuplet, each note's written duration = beat_dur / normal_count
            # but actual duration = beat_dur / positions_per_beat
            # MusicXML: duration = actual, type = written note type
            return {
                "ts": (beats, beat_type),
                "unit": total_dur // 12,  # actual duration per grid position
                "tup": True,
                "wtype": note_type,
                "ta": positions_per_beat,
                "tn": normal_count,
                "group_type": _note_type_for_duration(beat_dur)[0],
                "group_dur": beat_dur,
                "custom": False,
            }
    else:
        # Non-uniform distribution: need beat-by-beat rendering
        # Build per-beat info
        beat_info = []
        for g in groups:
            if g == 0:
                beat_info.append({
                    "positions": 0,
                    "beat_dur": beat_dur,
                    "tup": False,
                    "unit": beat_dur,
                    "wtype": _note_type_for_duration(beat_dur)[0],
                })
                continue

            unit_dur = beat_dur // g
            remainder = beat_dur % g

            if remainder == 0 and unit_dur in DIVS_TO_NOTE_TYPE:
                # Clean division
                beat_info.append({
                    "positions": g,
                    "beat_dur": beat_dur,
                    "tup": False,
                    "unit": unit_dur,
                    "wtype": DIVS_TO_NOTE_TYPE[unit_dur],
                })
            else:
                # Tuplet needed
                normal_count = _closest_standard(g)
                normal_dur = beat_dur // normal_count if normal_count > 0 else beat_dur
                note_type, _ = _note_type_for_duration(normal_dur)
                beat_info.append({
                    "positions": g,
                    "beat_dur": beat_dur,
                    "tup": True,
                    "unit": beat_dur // g if g > 0 else beat_dur,
                    "wtype": note_type,
                    "ta": g,
                    "tn": normal_count,
                    "group_type": _note_type_for_duration(beat_dur)[0],
                    "group_dur": beat_dur,
                })

        return {
            "ts": (beats, beat_type),
            "unit": total_dur // 12,  # average unit (used for rest decomposition)
            "tup": True,  # signal that this needs special handling
            "wtype": beat_info[0]["wtype"],
            "custom": True,
            "beat_info": beat_info,
            "groups": groups,
        }


def parse_custom_ts_types(s):
    """Parse a string like '3/8, 5/8, 7/8, 3/4, 4/4, 12/4' into a list
    of (beats, beat_type) tuples."""
    s = s.replace(",", " ").replace(";", " ")
    tokens = s.strip().split()
    result = []
    for t in tokens:
        if "/" not in t:
            raise ValueError(f"Invalid time signature format: '{t}' (expected N/M)")
        parts = t.split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid time signature: '{t}'")
        beats = int(parts[0])
        beat_type = int(parts[1])
        if beats < 1 or beats > 99:
            raise ValueError(f"Invalid number of beats: {beats}")
        if beat_type not in (1, 2, 4, 8, 16, 32):
            raise ValueError(f"Invalid beat type: {beat_type} (must be 1,2,4,8,16,32)")
        result.append((beats, beat_type))
    if not result:
        raise ValueError("No time signatures provided")
    return result


def build_custom_ts_defs(ts_types_str):
    """Build a custom TS_DEFS dict from a string of time signatures.
    Returns (custom_ts_defs, n_types) where custom_ts_defs maps
    1-based index to TS def dicts."""
    ts_types = parse_custom_ts_types(ts_types_str)
    custom_defs = {}
    for i, (beats, beat_type) in enumerate(ts_types):
        custom_defs[i + 1] = build_custom_ts_def(beats, beat_type)
    return custom_defs, len(ts_types)


def parse_ts_sequence_custom(s, max_type):
    """Parse a TS sequence string for custom types (1-based indices)."""
    s = s.replace(",", " ")
    tokens = s.strip().split()
    if not tokens:
        raise ValueError("Time signature sequence cannot be empty")
    result = []
    for t in tokens:
        v = int(t)
        if not 1 <= v <= max_type:
            raise ValueError(
                f"TS type {v} out of range 1-{max_type} "
                f"(you defined {max_type} custom types)")
        result.append(v)
    return result


# ===================================================================
# STAGE 1 -- Row Generation
# ===================================================================

def build_permutation_matrix(perm_pattern):
    matrix = [list(range(12))]
    for k in range(1, 12):
        prev = matrix[k - 1]
        matrix.append([prev[perm_pattern[i]] for i in range(12)])
    return matrix


def compute_onsets(duration_list):
    onsets = [abs(duration_list[0])]
    for j in range(1, 12):
        onsets.append(onsets[-1] + duration_list[j])
    return onsets


def derive_rhythm_row(pitch_row, perm_matrix, onsets):
    concat = [val for row in perm_matrix for val in row]
    rhythm_row = [None] * 12
    for i in range(12):
        if onsets[i] >= len(concat):
            raise ValueError(
                f"Onset {onsets[i]} exceeds matrix size {len(concat)}. "
                f"Duration list may be too large.")
        address = concat[onsets[i]]
        if rhythm_row[address] is not None:
            raise ValueError(
                f"Collision at slot {address}: "
                f"{pc_name(rhythm_row[address])} vs {pc_name(pitch_row[i])}")
        rhythm_row[address] = pitch_row[i]
    if None in rhythm_row:
        missing = [j for j, x in enumerate(rhythm_row) if x is None]
        raise ValueError(f"Rhythm row incomplete - empty slots: {missing}")
    return rhythm_row


def generate_permutations(source_row, perm_matrix):
    return [
        [source_row[perm_matrix[k][i]] for i in range(12)]
        for k in range(12)
    ]


def run_stage1(pitch_row, perm_pattern, duration_list):
    matrix = build_permutation_matrix(perm_pattern)
    onsets = compute_onsets(duration_list)
    rhythm_row = derive_rhythm_row(pitch_row, matrix, onsets)
    pitch_perms = generate_permutations(pitch_row, matrix)
    rhythm_perms = generate_permutations(rhythm_row, matrix)
    return {
        "pitch_row": pitch_row,
        "rhythm_row": rhythm_row,
        "perm_matrix": matrix,
        "onsets": onsets,
        "pitch_perms": pitch_perms,
        "rhythm_perms": rhythm_perms,
    }


# ===================================================================
# STAGE 2 -- Zeitnetz V1 (circular scanning)
# ===================================================================

def run_stage2(s1):
    rhythm_tape = []
    pitch_targets = []
    for k in range(12):
        rhythm_tape.extend(s1["rhythm_perms"][k])
        pitch_targets.extend(s1["pitch_perms"][k])
    tape_len = len(rhythm_tape)

    cursor = 0
    flat = []
    for i in range(tape_len):
        target_pc = pitch_targets[i]
        count = 0
        scan = cursor
        while True:
            scan = (scan + 1) % tape_len
            count += 1
            if rhythm_tape[scan] == target_pc:
                break
        flat.append(count)
        cursor = scan

    initial_rest = flat[0]
    voices = []
    for k in range(12):
        start = 1 + k * 12
        durs = flat[start: start + 12]
        if len(durs) < 12:
            # flat[i] scans for pitch_targets[i]; the missing value is
            # flat[1 + k*12 + len(durs)], which wraps to target index 0.
            target_pc = pitch_targets[(1 + k * 12 + len(durs)) % tape_len]
            count = 0
            scan = cursor
            while True:
                scan = (scan + 1) % tape_len
                count += 1
                if rhythm_tape[scan] == target_pc:
                    break
            durs.append(count)
            cursor = scan

        pitches = s1["pitch_perms"][k]
        notes = [(pitches[i], durs[i]) for i in range(12)]
        voices.append({
            "voice_index": k,
            "pitch_perm": pitches,
            "rhythm_perm": s1["rhythm_perms"][k],
            "initial_rest_32nds": initial_rest if k == 0 else 0,
            "notes": notes,
        })
    return voices


# ===================================================================
# STAGE 3 -- Sound Families
# ===================================================================

def run_stage3_1(s1):
    control_row = s1["pitch_perms"][CONTROL_ROW_INDEX]
    result = []
    for i in range(12):
        rr = s1["rhythm_perms"][i]
        target = control_row[i]
        pitches = []
        for pc in rr:
            pitches.append(pc)
            if pc == target:
                break
        result.append({
            "row_index": i,
            "target_pc": target,
            "pitches": pitches,
            "rhythm_row": rr,
        })
    return result


def run_stage3_2(s3_1):
    by_row = {rf["row_index"]: rf for rf in s3_1}
    start_pitches = []
    for ri in FAMILY_ROW_ORDER:
        for pc in by_row[ri]["pitches"]:
            start_pitches.append((ri, pc))

    end_tape = []
    for ri in END_PITCH_ROW_ORDER:
        for pc in reversed(by_row[ri]["pitches"]):
            end_tape.append(pc)

    n_families = len(start_pitches)
    families = []
    for i in range(n_families):
        row_idx, spc = start_pitches[i]
        families.append({
            "family": i + 1,
            "start_pc": spc,
            "end_pc": end_tape[i],
            "row": row_idx,
        })
    return families


def run_stage3(s1):
    s3_1 = run_stage3_1(s1)
    families = run_stage3_2(s3_1)
    return s3_1, families


# ===================================================================
# ZEITNETZ GRID
# ===================================================================

def build_row_templates(voices):
    return [
        (v["voice_index"], v["initial_rest_32nds"], list(v["notes"]))
        for v in voices
    ]


def build_grid(row_templates, min_events=0, max_cycles=None):
    if max_cycles is None:
        max_cycles = MAX_CYCLES
    events = []
    row_start_pos = {}
    pos = 0
    idx = 0

    for vi, ir, notes in row_templates:
        if ir > 0:
            pos += ir
        label = f"Row {vi}"
        row_start_pos[label] = pos
        for pc, dur_32 in notes:
            events.append({"pos": pos, "pc": pc, "dur": dur_32,
                           "label": label, "index": idx})
            pos += dur_32
            idx += 1

    cycle = 0
    while cycle < max_cycles and len(events) < min_events:
        cycle += 1
        suffix = chr(ord('a') + cycle - 1)
        for vi, _ir, notes in row_templates:
            label = f"Row {vi}{suffix}"
            row_start_pos[label] = pos
            for pc, dur_32 in notes:
                events.append({"pos": pos, "pc": pc, "dur": dur_32,
                               "label": label, "index": idx})
                pos += dur_32
                idx += 1

    return events, row_start_pos, pos, cycle


def test_all_families_done(zn_events, families):
    family_queue = list(families)
    active = []
    fam_evt_count = {}

    for ev in zn_events:
        if family_queue and family_queue[0]["start_pc"] == ev["pc"]:
            f = family_queue.pop(0)
            active.append(f)
            fam_evt_count[f["family"]] = 0

        for f in active:
            fam_evt_count[f["family"]] += 1

        new_active = []
        for f in active:
            if f["end_pc"] == ev["pc"]:
                if f["start_pc"] == f["end_pc"]:
                    if fam_evt_count[f["family"]] >= 2:
                        continue
                    else:
                        new_active.append(f)
                else:
                    continue
            else:
                new_active.append(f)
        active = new_active

        if not family_queue and not active:
            return True
    return False


def build_grid_until_families_done(row_templates, families, max_cycles=None):
    if max_cycles is None:
        max_cycles = MAX_CYCLES
    events = []
    row_start_pos = {}
    pos = 0
    idx = 0

    for vi, ir, notes in row_templates:
        if ir > 0:
            pos += ir
        label = f"Row {vi}"
        row_start_pos[label] = pos
        for pc, dur_32 in notes:
            events.append({"pos": pos, "pc": pc, "dur": dur_32,
                           "label": label, "index": idx})
            pos += dur_32
            idx += 1

    if test_all_families_done(events, families):
        return events, row_start_pos, pos, 0, True

    for cycle in range(1, max_cycles + 1):
        suffix = chr(ord('a') + cycle - 1)
        for vi, _ir, notes in row_templates:
            label = f"Row {vi}{suffix}"
            row_start_pos[label] = pos
            for pc, dur_32 in notes:
                events.append({"pos": pos, "pc": pc, "dur": dur_32,
                               "label": label, "index": idx})
                pos += dur_32
                idx += 1
        if test_all_families_done(events, families):
            return events, row_start_pos, pos, cycle, True

    return events, row_start_pos, pos, max_cycles, False


# ===================================================================
# FAMILY SCAN
# ===================================================================

def sequential_scan(zn_events, families):
    family_queue = list(families)
    active = []
    fam_entries = {f["family"]: [] for f in families}
    fam_evt_count = {}

    for ev in zn_events:
        if family_queue and family_queue[0]["start_pc"] == ev["pc"]:
            f = family_queue.pop(0)
            active.append(f)
            fam_evt_count[f["family"]] = 0

        for f in active:
            fam_entries[f["family"]].append({
                "zn_index": ev["index"], "pos": ev["pos"],
                "pc": ev["pc"], "dur": ev["dur"]
            })
            fam_evt_count[f["family"]] += 1

        new_active = []
        for f in active:
            if f["end_pc"] == ev["pc"]:
                if f["start_pc"] == f["end_pc"]:
                    if fam_evt_count[f["family"]] >= 2:
                        continue
                    else:
                        new_active.append(f)
                else:
                    continue
            else:
                new_active.append(f)
        active = new_active

        if not family_queue and not active:
            break

    all_done = (not family_queue) and (not active)
    return fam_entries, all_done, family_queue


def duration_as_count_transform(fam_entries, zn_events):
    final_entries = {}
    max_index = 0

    for fn, entries in fam_entries.items():
        if not entries:
            final_entries[fn] = []
            continue
        start_idx = entries[0]["zn_index"]
        durations = [e["dur"] for e in entries]
        new_entries = []
        idx = start_idx
        for i in range(len(entries)):
            if idx >= len(zn_events):
                break
            ev = zn_events[idx]
            new_entries.append({
                "zn_index": idx, "pos": ev["pos"],
                "pc": ev["pc"], "dur": ev["dur"]
            })
            max_index = max(max_index, idx)
            if i < len(entries) - 1:
                idx += durations[i]
                max_index = max(max_index, idx)
        final_entries[fn] = new_entries

    return final_entries, max_index


# ===================================================================
# STAFF ASSIGNMENT
# ===================================================================

def round_robin(n_families, n_staves=12):
    return {fn: ((fn - 1) % n_staves) + 1 for fn in range(1, n_families + 1)}


def greedy_assign(family_spans):
    sorted_spans = sorted(family_spans, key=lambda x: x[1])
    staff_ends = []
    assignment = {}
    for fn, start, end in sorted_spans:
        placed = False
        for si in range(len(staff_ends)):
            if start > staff_ends[si]:
                staff_ends[si] = end
                assignment[fn] = si + 1
                placed = True
                break
        if not placed:
            staff_ends.append(end)
            assignment[fn] = len(staff_ends)
    return assignment, len(staff_ends)


# ===================================================================
# STAGE 4 -- Full Score
# ===================================================================

def run_stage4(voices, families):
    templates = build_row_templates(voices)
    zn_events, row_start_pos, total_32, n_cycles, all_done = \
        build_grid_until_families_done(templates, families)
    fam_entries, scan_done, remaining = sequential_scan(zn_events, families)
    activated_fams = [f for f in families if len(fam_entries[f["family"]]) > 0]
    n_activated = len(activated_fams)
    n_families = len(families)
    n_staves = min(12, n_families)
    assign = round_robin(n_families, n_staves)
    n_bars = (total_32 + BAR - 1) // BAR

    return {
        "zn_events": zn_events,
        "row_start_pos": row_start_pos,
        "total_32": total_32,
        "n_bars": n_bars,
        "n_cycles": n_cycles,
        "fam_entries": fam_entries,
        "n_families": n_families,
        "n_activated": n_activated,
        "all_done": all_done and scan_done,
        "staff_assign": assign,
        "n_staves": n_staves,
        "remaining_queue": remaining,
    }


# ===================================================================
# STAGE 5 -- Final (duration-as-count)
# ===================================================================

def run_stage5(voices, families, s4):
    templates = build_row_templates(voices)
    _, max_idx = duration_as_count_transform(s4["fam_entries"], s4["zn_events"])
    min_events_needed = max_idx + 1
    zn_events, row_start_pos, total_32, n_cycles = build_grid(
        templates, min_events=min_events_needed, max_cycles=MAX_CYCLES)

    while max_idx >= len(zn_events):
        zn_events, row_start_pos, total_32, n_cycles = build_grid(
            templates, min_events=max_idx + 100, max_cycles=MAX_CYCLES + 10)

    final_entries, max_idx = duration_as_count_transform(
        s4["fam_entries"], zn_events)

    max_pos = 0
    for fn, entries in final_entries.items():
        if entries:
            max_pos = max(max_pos, entries[-1]["pos"])

    spans = []
    for fn, entries in final_entries.items():
        if entries:
            spans.append((fn, entries[0]["pos"], entries[-1]["pos"]))
    assign, n_staves = greedy_assign(spans)

    score_total = max_pos + BAR
    n_bars = (score_total + BAR - 1) // BAR

    return {
        "zn_events": zn_events,
        "row_start_pos": row_start_pos,
        "total_32": total_32,
        "n_bars": n_bars,
        "n_cycles": n_cycles,
        "final_entries": final_entries,
        "staff_assign": assign,
        "n_staves": n_staves,
        "max_grid_pos": max_pos,
    }


# ===================================================================
# VALIDATION & DISCOVERY
# ===================================================================

def validate_inputs(pitch_row, perm_pattern, duration_list):
    errors = []
    warnings = []

    if len(pitch_row) != 12:
        errors.append(f"Pitch row must have 12 values, got {len(pitch_row)}")
    elif set(pitch_row) != set(range(12)):
        errors.append("Pitch row must contain each class 0-11 exactly once")

    if len(perm_pattern) != 12:
        errors.append(f"Permutation must have 12 values, got {len(perm_pattern)}")
    elif set(perm_pattern) != set(range(12)):
        errors.append("Permutation must be a valid permutation of 0-11")
    else:
        if perm_pattern == list(range(12)):
            warnings.append("Identity permutation: all matrix rows will be identical")

    if len(duration_list) != 13:
        errors.append(f"Duration list must have 13 values, got {len(duration_list)}")
    else:
        if 0 in duration_list[1:]:
            errors.append("Duration list contains zero values (positions 1-12)")
        if any(abs(d) > 100 for d in duration_list):
            warnings.append("Duration list contains very large values (>100)")
        onsets = [abs(duration_list[0])]
        for j in range(1, 12):
            onsets.append(onsets[-1] + duration_list[j])
        if any(o >= 144 for o in onsets):
            errors.append(f"Onset {max(onsets)} exceeds matrix size 144.")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def test_viability(pitch_row, perm_pattern, duration_list, max_cycles=None):
    if max_cycles is None:
        max_cycles = MAX_CYCLES

    result = {
        "viable": False, "n_families": 0, "n_same_pitch": 0,
        "n_cycles_needed": -1, "n_activated": 0, "stage1_ok": False,
        "stage1_error": None, "families_per_row": {}, "details": "",
    }

    try:
        s1 = run_stage1(pitch_row, perm_pattern, duration_list)
        result["stage1_ok"] = True
    except ValueError as e:
        result["stage1_error"] = str(e)
        result["details"] = f"Stage 1 failed: {e}"
        return result

    s2 = run_stage2(s1)
    s3_1, families = run_stage3(s1)
    n_families = len(families)
    result["n_families"] = n_families

    for rf in s3_1:
        result["families_per_row"][rf["row_index"]] = len(rf["pitches"])

    same_pitch = [f for f in families if f["start_pc"] == f["end_pc"]]
    result["n_same_pitch"] = len(same_pitch)

    if n_families == 0:
        result["details"] = "No families generated"
        return result

    templates = build_row_templates(s2)
    events, _, _, n_cycles, done = build_grid_until_families_done(
        templates, families, max_cycles=max_cycles)
    if done:
        result["viable"] = True
        result["n_cycles_needed"] = n_cycles
        result["n_activated"] = n_families

    lines = [f"Families: {n_families}",
             f"Same-pitch families: {len(same_pitch)}"]
    if same_pitch:
        sp_names = ", ".join(
            f"F{f['family']}({pc_name(f['start_pc'])})" for f in same_pitch)
        lines.append(f"  ({sp_names})")
    for ri in FAMILY_ROW_ORDER:
        count = result["families_per_row"].get(ri, 0)
        lines.append(f"  Row {ri:2d}: {count} families")
    if result["viable"]:
        lines.append(f"Viable: YES - {n_families} families, "
                     f"{result['n_cycles_needed']} extra cycle(s)")
    else:
        lines.append(f"Viable: NO - only {result['n_activated']}/{n_families} "
                     f"activated after {max_cycles} cycles")
    result["details"] = "\n".join(lines)
    return result


def suggest_repairs(pitch_row, perm_pattern, duration_list, max_attempts=24):
    results = []
    for offset in range(1, 13):
        new_durs = [duration_list[0]] + [
            duration_list[1 + (i + offset) % 12] for i in range(12)]
        try:
            v = test_viability(pitch_row, perm_pattern, new_durs, max_cycles=10)
            if v["viable"]:
                results.append({
                    "type": "duration_rotation", "offset": offset,
                    "pitch_row": pitch_row, "perm_pattern": perm_pattern,
                    "duration_list": new_durs, "viability": v,
                })
        except (ValueError, IndexError):
            pass

    for offset in range(1, 12):
        new_row = [(pc + offset) % 12 for pc in pitch_row]
        try:
            v = test_viability(new_row, perm_pattern, duration_list, max_cycles=10)
            if v["viable"]:
                results.append({
                    "type": "pitch_transposition", "offset": offset,
                    "pitch_row": new_row, "perm_pattern": perm_pattern,
                    "duration_list": duration_list, "viability": v,
                })
        except (ValueError, IndexError):
            pass

    results.sort(key=lambda r: (r["viability"]["n_cycles_needed"],
                                -r["viability"]["n_families"]))
    return results[:max_attempts]


def find_valid_duration_list(perm_pattern, rng=None, max_attempts=500):
    rng = rng or random
    matrix = build_permutation_matrix(perm_pattern)
    concat = [val for row in matrix for val in row]

    positions_by_value = {v: [] for v in range(12)}
    for i, v in enumerate(concat):
        positions_by_value[v].append(i)

    for _ in range(max_attempts):
        chosen = []
        for v in range(12):
            chosen.append(rng.choice(positions_by_value[v]))
        chosen.sort()
        values = [concat[p] for p in chosen]
        if len(set(values)) != 12:
            continue
        first = -chosen[0]
        rest = [chosen[i+1] - chosen[i] for i in range(11)]
        rest.append(rng.randint(1, 10))
        if all(d > 0 for d in rest[:11]):
            return [first] + rest
    return None


def discover(n_trials=100, seed=None, min_families=30, max_cycles=10):
    rng = random.Random(seed)
    results = []
    viable_count = 0
    stage1_pass = 0
    log_lines = []

    for trial in range(n_trials):
        pitch_row = list(range(12))
        rng.shuffle(pitch_row)
        perm_pattern = list(range(12))
        rng.shuffle(perm_pattern)

        duration_list = find_valid_duration_list(perm_pattern, rng)
        if duration_list is None:
            continue
        stage1_pass += 1

        try:
            v = test_viability(pitch_row, perm_pattern, duration_list,
                               max_cycles=max_cycles)
        except (ValueError, IndexError):
            continue

        if not v["stage1_ok"]:
            continue

        if v["viable"] and v["n_families"] >= min_families:
            viable_count += 1
            result = {
                "trial": trial,
                "pitch_row": pitch_row,
                "perm_pattern": perm_pattern,
                "duration_list": duration_list,
                "n_families": v["n_families"],
                "n_same_pitch": v["n_same_pitch"],
                "n_cycles_needed": v["n_cycles_needed"],
            }
            results.append(result)
            row_str = " ".join(pc_name(p) for p in pitch_row)
            log_lines.append(
                f"  Trial {trial:4d}: {v['n_families']} families, "
                f"{v['n_cycles_needed']} cycles | {row_str}")

        if (trial + 1) % 25 == 0:
            log_lines.append(
                f"  ... {trial+1}/{n_trials} tested, "
                f"{viable_count} viable, {stage1_pass} passed Stage 1")

    results.sort(key=lambda r: -r["n_families"])

    log_lines.append(f"\nDiscovery complete: {viable_count}/{n_trials} viable "
                     f"(>= {min_families} families)")
    if results:
        best = results[0]
        log_lines.append(f"Best: {best['n_families']} families, "
                         f"{best['n_cycles_needed']} cycles")
        log_lines.append(
            f"  Pitches:   {' '.join(str(p) for p in best['pitch_row'])}")
        log_lines.append(
            f"  Perm:      {' '.join(str(p) for p in best['perm_pattern'])}")
        log_lines.append(
            f"  Durations: {' '.join(str(d) for d in best['duration_list'])}")

    return results, "\n".join(log_lines)


def discover_by_families(target_families, tolerance=0, n_trials=500,
                         seed=None, max_cycles=10):
    """Discover input combinations that produce exactly target_families
    (within +/- tolerance) families."""
    rng = random.Random(seed)
    results = []
    tested = 0
    stage1_pass = 0
    log_lines = []

    lo = target_families - tolerance
    hi = target_families + tolerance

    for trial in range(n_trials):
        pitch_row = list(range(12))
        rng.shuffle(pitch_row)
        perm_pattern = list(range(12))
        rng.shuffle(perm_pattern)

        duration_list = find_valid_duration_list(perm_pattern, rng)
        if duration_list is None:
            continue
        stage1_pass += 1

        try:
            v = test_viability(pitch_row, perm_pattern, duration_list,
                               max_cycles=max_cycles)
        except (ValueError, IndexError):
            continue

        if not v["stage1_ok"]:
            continue

        tested += 1
        n_fam = v["n_families"]

        if v["viable"] and lo <= n_fam <= hi:
            result = {
                "trial": trial,
                "pitch_row": pitch_row,
                "perm_pattern": perm_pattern,
                "duration_list": duration_list,
                "n_families": n_fam,
                "n_same_pitch": v["n_same_pitch"],
                "n_cycles_needed": v["n_cycles_needed"],
                "distance": abs(n_fam - target_families),
            }
            results.append(result)
            row_str = " ".join(pc_name(p) for p in pitch_row)
            log_lines.append(
                f"  Trial {trial:4d}: {n_fam} families, "
                f"{v['n_cycles_needed']} cycles | {row_str}")

        if (trial + 1) % 50 == 0:
            log_lines.append(
                f"  ... {trial+1}/{n_trials} tested, "
                f"{len(results)} matches, {stage1_pass} passed Stage 1")

    # Sort by distance to target, then by fewer cycles
    results.sort(key=lambda r: (r["distance"], r["n_cycles_needed"]))

    log_lines.append(
        f"\nDiscovery complete: {len(results)}/{n_trials} match "
        f"target {target_families} +/- {tolerance}")
    if results:
        best = results[0]
        log_lines.append(
            f"Best: {best['n_families']} families, "
            f"{best['n_cycles_needed']} cycles")
        log_lines.append(
            f"  Pitches:   {' '.join(str(p) for p in best['pitch_row'])}")
        log_lines.append(
            f"  Perm:      {' '.join(str(p) for p in best['perm_pattern'])}")
        log_lines.append(
            f"  Durations: {' '.join(str(d) for d in best['duration_list'])}")

    return results, "\n".join(log_lines)


# ===================================================================
# MUSICXML WRITER (pure Python, no music21)
# ===================================================================

DIVISIONS = 24  # per quarter note


def _xml_header():
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE score-partwise PUBLIC '
            '"-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">\n')


def _add_pitch(note_el, pc):
    step, alter, octave = PC_TO_XML_PITCH[pc]
    pitch_el = SubElement(note_el, "pitch")
    SubElement(pitch_el, "step").text = step
    if alter != 0:
        SubElement(pitch_el, "alter").text = str(alter)
    SubElement(pitch_el, "octave").text = str(octave)


def _add_note_xml(measure, pc, duration, note_type, dotted=False,
                  is_tuplet=False, tup_actual=3, tup_normal=2,
                  tup_start=False, tup_stop=False,
                  lyric_text=None, is_rest=False):
    """Add a note or rest to a measure element."""
    note_el = SubElement(measure, "note")
    if is_rest:
        SubElement(note_el, "rest")
    else:
        _add_pitch(note_el, pc)
    SubElement(note_el, "duration").text = str(duration)
    if note_type:
        SubElement(note_el, "type").text = note_type
    if dotted:
        SubElement(note_el, "dot")
    if is_tuplet:
        tm = SubElement(note_el, "time-modification")
        SubElement(tm, "actual-notes").text = str(tup_actual)
        SubElement(tm, "normal-notes").text = str(tup_normal)
    if tup_start or tup_stop:
        notations = SubElement(note_el, "notations")
        if tup_start:
            SubElement(notations, "tuplet", type="start", number="1")
        if tup_stop:
            SubElement(notations, "tuplet", type="stop", number="1")
    if lyric_text is not None:
        lyric = SubElement(note_el, "lyric", number="1")
        SubElement(lyric, "syllabic").text = "single"
        SubElement(lyric, "text").text = str(lyric_text)


def _build_part_uniform(part_el, notes_sorted, n_bars,
                        labels_dict=None, lyric_fn=None):
    """Build measures with uniform 3/8 time signature."""
    ni = 0
    unit = 3  # 32nd note in divisions

    for b in range(n_bars):
        m = SubElement(part_el, "measure", number=str(b + 1))

        if b == 0:
            attr = SubElement(m, "attributes")
            SubElement(attr, "divisions").text = str(DIVISIONS)
            time_el = SubElement(attr, "time")
            SubElement(time_el, "beats").text = "3"
            SubElement(time_el, "beat-type").text = "8"
            clef_el = SubElement(attr, "clef")
            SubElement(clef_el, "sign").text = "G"
            SubElement(clef_el, "line").text = "2"

        bs = b * BAR
        be = bs + BAR

        # Labels as direction text
        if labels_dict:
            for lp, lt in labels_dict.items():
                if bs <= lp < be:
                    direction = SubElement(m, "direction", placement="above")
                    dt = SubElement(direction, "direction-type")
                    SubElement(dt, "words").text = lt

        cur = bs
        while cur < be:
            if ni < len(notes_sorted) and notes_sorted[ni][0] == cur:
                entry = notes_sorted[ni]
                lyr = lyric_fn(entry) if lyric_fn else None
                _add_note_xml(m, entry[1], unit, "32nd", lyric_text=lyr)
                cur += 1
                ni += 1
            else:
                nxt = notes_sorted[ni][0] if ni < len(notes_sorted) else be
                gap = min(nxt, be) - cur
                if gap > 0:
                    rest_dur = gap * unit
                    parts = decompose_duration(rest_dur)
                    for d, t, dot in parts:
                        _add_note_xml(m, 0, d, t, dotted=dot, is_rest=True)
                    cur += gap


        # Final barline on last measure
        if b == n_bars - 1:
            barline = SubElement(m, "barline", location="right")
            SubElement(barline, "bar-style").text = "light-heavy"


def _build_part_v2(part_el, notes_sorted, n_bars, ts_sequence,
                   labels_dict=None, lyric_fn=None, ts_defs=None):
    """Build measures with variable time signatures.
    If ts_defs is provided, use those instead of the global TS_DEFS."""
    if ts_defs is None:
        ts_defs = TS_DEFS

    ni = 0
    prev_ts = None

    for b in range(n_bars):
        ts_idx = get_ts_for_bar(b, ts_sequence)
        td = ts_defs[ts_idx]
        ts = td["ts"]
        unit = td["unit"]
        is_tup = td["tup"]
        wtype = td["wtype"]
        is_custom_beat = td.get("custom", False)

        m = SubElement(part_el, "measure", number=str(b + 1))

        # Attributes
        if ts != prev_ts or b == 0:
            attr = SubElement(m, "attributes")
            if b == 0:
                SubElement(attr, "divisions").text = str(DIVISIONS)
            time_el = SubElement(attr, "time")
            SubElement(time_el, "beats").text = str(ts[0])
            SubElement(time_el, "beat-type").text = str(ts[1])
            if b == 0:
                clef_el = SubElement(attr, "clef")
                SubElement(clef_el, "sign").text = "G"
                SubElement(clef_el, "line").text = "2"
            prev_ts = ts

        bs = b * BAR

        # Labels
        if labels_dict:
            for lp, lt in labels_dict.items():
                if bs <= lp < bs + BAR:
                    direction = SubElement(m, "direction", placement="above")
                    dt = SubElement(direction, "direction-type")
                    SubElement(dt, "words").text = lt

        # Collect 12 slots
        slots = []
        for g in range(BAR):
            gpos = bs + g
            if ni < len(notes_sorted) and notes_sorted[ni][0] == gpos:
                slots.append(notes_sorted[ni])
                ni += 1
            else:
                slots.append(None)

        if is_custom_beat and "beat_info" in td:
            # Custom time signature with non-uniform beat grouping
            _render_custom_beat_measure(m, slots, td, lyric_fn)
        elif not is_tup:
            # Non-tuplet bar (uniform)
            i = 0
            while i < BAR:
                if slots[i] is not None:
                    entry = slots[i]
                    lyr = lyric_fn(entry) if lyric_fn else None
                    _add_note_xml(m, entry[1], unit, wtype, lyric_text=lyr)
                    i += 1
                else:
                    count = 0
                    while i < BAR and slots[i] is None:
                        count += 1
                        i += 1
                    rest_dur = count * unit
                    parts = decompose_duration(rest_dur)
                    for d, t, dot in parts:
                        _add_note_xml(m, 0, d, t, dotted=dot, is_rest=True)
        else:
            # Tuplet bar: groups of 3 (standard TS_DEFS tuplet types)
            ta = td["ta"]
            tn = td["tn"]
            group_type = td["group_type"]
            group_dur = td["group_dur"]

            for g_start in range(0, BAR, 3):
                group = slots[g_start:g_start + 3]

                if all(s is None for s in group):
                    # Full group rest (no tuplet notation)
                    _add_note_xml(m, 0, group_dur, group_type, is_rest=True)
                    continue

                # Mixed group: need tuplet notation
                elements = []  # (is_rest, pc, count)
                j = 0
                while j < 3:
                    if group[j] is not None:
                        elements.append(("note", group[j]))
                        j += 1
                    else:
                        rcount = 0
                        while j < 3 and group[j] is None:
                            rcount += 1
                            j += 1
                        elements.append(("rest", rcount))

                for idx, el in enumerate(elements):
                    is_start = (idx == 0)
                    is_stop = (idx == len(elements) - 1)

                    if el[0] == "note":
                        entry = el[1]
                        lyr = lyric_fn(entry) if lyric_fn else None
                        _add_note_xml(
                            m, entry[1], unit, wtype,
                            is_tuplet=True, tup_actual=ta, tup_normal=tn,
                            tup_start=is_start, tup_stop=is_stop,
                            lyric_text=lyr)
                    else:
                        rcount = el[1]
                        for ri in range(rcount):
                            is_s = is_start and ri == 0
                            is_e = is_stop and ri == rcount - 1
                            _add_note_xml(
                                m, 0, unit, wtype,
                                is_tuplet=True, tup_actual=ta, tup_normal=tn,
                                tup_start=is_s, tup_stop=is_e,
                                is_rest=True)

        # Final barline
        if b == n_bars - 1:
            barline = SubElement(m, "barline", location="right")
            SubElement(barline, "bar-style").text = "light-heavy"


def _render_custom_beat_measure(m, slots, td, lyric_fn):
    """Render a measure with non-uniform beat groupings (custom TS)."""
    beat_info = td["beat_info"]
    groups = td["groups"]
    slot_idx = 0

    for bi, binfo in enumerate(beat_info):
        n_pos = binfo["positions"]
        if n_pos == 0:
            # Empty beat - write a rest for the beat duration
            beat_dur = binfo["beat_dur"]
            bt, bdot = _note_type_for_duration(beat_dur)
            _add_note_xml(m, 0, beat_dur, bt, dotted=bdot, is_rest=True)
            continue

        beat_slots = slots[slot_idx:slot_idx + n_pos]
        slot_idx += n_pos

        b_unit = binfo["unit"]
        b_wtype = binfo["wtype"]
        b_tup = binfo["tup"]

        if not b_tup:
            # No tuplet needed for this beat
            i = 0
            while i < n_pos:
                if beat_slots[i] is not None:
                    entry = beat_slots[i]
                    lyr = lyric_fn(entry) if lyric_fn else None
                    _add_note_xml(m, entry[1], b_unit, b_wtype, lyric_text=lyr)
                    i += 1
                else:
                    count = 0
                    while i < n_pos and beat_slots[i] is None:
                        count += 1
                        i += 1
                    rest_dur = count * b_unit
                    parts = decompose_duration(rest_dur)
                    for d, t, dot in parts:
                        _add_note_xml(m, 0, d, t, dotted=dot, is_rest=True)
        else:
            # Tuplet beat
            b_ta = binfo["ta"]
            b_tn = binfo["tn"]
            b_group_type = binfo.get("group_type", b_wtype)
            b_group_dur = binfo.get("group_dur", binfo["beat_dur"])

            if all(s is None for s in beat_slots):
                # All rest - write a single beat rest (no tuplet)
                _add_note_xml(m, 0, b_group_dur, b_group_type, is_rest=True)
                continue

            # Build elements for this beat's tuplet
            elements = []
            j = 0
            while j < n_pos:
                if beat_slots[j] is not None:
                    elements.append(("note", beat_slots[j]))
                    j += 1
                else:
                    rcount = 0
                    while j < n_pos and beat_slots[j] is None:
                        rcount += 1
                        j += 1
                    elements.append(("rest", rcount))

            for idx, el in enumerate(elements):
                is_start = (idx == 0)
                is_stop = (idx == len(elements) - 1)

                if el[0] == "note":
                    entry = el[1]
                    lyr = lyric_fn(entry) if lyric_fn else None
                    _add_note_xml(
                        m, entry[1], b_unit, b_wtype,
                        is_tuplet=True, tup_actual=b_ta, tup_normal=b_tn,
                        tup_start=is_start, tup_stop=is_stop,
                        lyric_text=lyr)
                else:
                    rcount = el[1]
                    for ri in range(rcount):
                        is_s = is_start and ri == 0
                        is_e = is_stop and ri == rcount - 1
                        _add_note_xml(
                            m, 0, b_unit, b_wtype,
                            is_tuplet=True, tup_actual=b_ta, tup_normal=b_tn,
                            tup_start=is_s, tup_stop=is_e,
                            is_rest=True)


def _build_score_xml(title, parts_data, use_v2=False, ts_sequence=None,
                     ts_defs=None):
    """Build a complete MusicXML score as a string.

    parts_data: list of (name, notes_sorted, n_bars, labels_dict, lyric_fn)
    ts_defs: optional custom TS definitions dict (if None, uses global TS_DEFS)
    """
    root = Element("score-partwise", version="4.0")

    work = SubElement(root, "work")
    SubElement(work, "work-title").text = title

    ident = SubElement(root, "identification")
    SubElement(ident, "creator", type="composer").text = "Zeitnetz Generator"

    part_list = SubElement(root, "part-list")

    for i, (name, _, _, _, _) in enumerate(parts_data):
        pid = f"P{i+1}"
        sp = SubElement(part_list, "score-part", id=pid)
        SubElement(sp, "part-name").text = name

    for i, (name, notes_sorted, n_bars, labels_dict, lyric_fn) in enumerate(parts_data):
        pid = f"P{i+1}"
        part_el = SubElement(root, "part", id=pid)

        if use_v2 and ts_sequence:
            _build_part_v2(part_el, notes_sorted, n_bars, ts_sequence,
                          labels_dict, lyric_fn, ts_defs=ts_defs)
        else:
            _build_part_uniform(part_el, notes_sorted, n_bars,
                               labels_dict, lyric_fn)

    # Convert to string
    from xml.etree.ElementTree import indent
    indent(root, space="  ")
    xml_str = _xml_header() + tostring(root, encoding="unicode")
    return xml_str


# ===================================================================
# EXPORT FUNCTIONS
# ===================================================================

def _prepare_staff_data(fam_entries, staff_assign, n_staves, n_bars,
                        entry_label_fn=None):
    """Build per-staff note lists and label dicts."""
    staff_notes = {s: [] for s in range(1, n_staves + 1)}
    staff_labels = {s: {} for s in range(1, n_staves + 1)}

    for fn, entries in fam_entries.items():
        if not entries:
            continue
        s = staff_assign.get(fn, 1)
        if s not in staff_notes:
            staff_notes[s] = []
            staff_labels[s] = {}
        for i, entry in enumerate(entries):
            if entry_label_fn:
                staff_notes[s].append(entry_label_fn(fn, i, entry))
            else:
                staff_notes[s].append((entry["pos"], entry["pc"], entry["dur"]))
            if i == 0:
                staff_labels[s][entry["pos"]] = f"F{fn}"

    for s in staff_notes:
        staff_notes[s].sort()

    return staff_notes, staff_labels


def export_stage4_xml(s4):
    """Generate Stage 4 MusicXML (uniform 3/8)."""
    zn_labels = {pos: label for label, pos in s4["row_start_pos"].items()}
    zn_sorted = [(ev["pos"], ev["pc"], ev["dur"]) for ev in s4["zn_events"]]

    staff_notes, staff_labels = _prepare_staff_data(
        s4["fam_entries"], s4["staff_assign"], s4["n_staves"], s4["n_bars"])

    parts = [("Zeitnetz", zn_sorted, s4["n_bars"], zn_labels,
              lambda e: str(e[2]))]

    for s in range(1, s4["n_staves"] + 1):
        parts.append((f"Staff {s}", staff_notes.get(s, []), s4["n_bars"],
                      staff_labels.get(s, {}), lambda e: str(e[2])))

    return _build_score_xml(
        "Full Score - Zeitnetz + Sound Families", parts)


def export_v2_xml(s4, ts_sequence, ts_defs=None):
    """Generate V2 MusicXML (variable time signatures)."""
    zn_labels = {pos: label for label, pos in s4["row_start_pos"].items()}
    zn_sorted = [(ev["pos"], ev["pc"], ev["dur"]) for ev in s4["zn_events"]]

    staff_notes, staff_labels = _prepare_staff_data(
        s4["fam_entries"], s4["staff_assign"], s4["n_staves"], s4["n_bars"])

    parts = [("Zeitnetz", zn_sorted, s4["n_bars"], zn_labels,
              lambda e: str(e[2]))]

    for s in range(1, s4["n_staves"] + 1):
        parts.append((f"Staff {s}", staff_notes.get(s, []), s4["n_bars"],
                      staff_labels.get(s, {}), lambda e: str(e[2])))

    return _build_score_xml(
        "Zeitnetz V2 - Variable Time Signatures", parts,
        use_v2=True, ts_sequence=ts_sequence, ts_defs=ts_defs)


def export_final_xml(s5, ts_sequence, ts_defs=None):
    """Generate Final MusicXML (duration-as-count)."""
    zn_labels = {pos: label for label, pos in s5["row_start_pos"].items()}
    max_pos = s5["n_bars"] * BAR
    zn_sorted = [(ev["pos"], ev["pc"], ev["dur"])
                 for ev in s5["zn_events"] if ev["pos"] < max_pos]

    # Staff data with F.E labels
    staff_notes = {s: [] for s in range(1, s5["n_staves"] + 1)}
    staff_labels = {s: {} for s in range(1, s5["n_staves"] + 1)}

    for fn, entries in s5["final_entries"].items():
        if not entries:
            continue
        s = s5["staff_assign"].get(fn, 1)
        if s not in staff_notes:
            staff_notes[s] = []
            staff_labels[s] = {}
        for i, entry in enumerate(entries):
            label = f"{fn}.{i+1}"
            staff_notes[s].append((entry["pos"], entry["pc"], entry["dur"], label))
            if i == 0:
                staff_labels[s][entry["pos"]] = f"F{fn}"

    for s in staff_notes:
        staff_notes[s].sort()

    parts = [("Zeitnetz", zn_sorted, s5["n_bars"], zn_labels,
              lambda e: str(e[2]))]

    for s in range(1, s5["n_staves"] + 1):
        parts.append((
            f"Staff {s}", staff_notes.get(s, []), s5["n_bars"],
            staff_labels.get(s, {}),
            lambda e: e[3] if len(e) > 3 else None
        ))

    return _build_score_xml(
        "Zeitnetz Final - Duration as Count", parts,
        use_v2=True, ts_sequence=ts_sequence, ts_defs=ts_defs)


# ===================================================================
# API FUNCTIONS (called from JavaScript)
# ===================================================================

def api_generate(pitches_str, perm_str, durations_str,
                 ts_mode="default", ts_custom_str="",
                 ts_types_mode="default", ts_types_custom_str=""):
    """Run full pipeline and return results as JSON string.

    ts_types_mode: "default" uses TS_DEFS, "custom" parses ts_types_custom_str
    ts_types_custom_str: e.g. "3/8, 5/8, 7/8, 3/4, 4/4, 12/4"
    """
    log = []
    files = {}

    try:
        # Parse inputs
        pitch_row = parse_pitch_input(pitches_str)
        perm_pattern = parse_int_list(perm_str, 12, "Permutation")
        duration_list = parse_int_list(durations_str, 13, "Durations")

        log.append("=== Input Parameters ===")
        log.append(f"Pitch row:  {' '.join(pc_name(p) for p in pitch_row)}")
        log.append(f"Perm:       {perm_pattern}")
        log.append(f"Durations:  {duration_list}")
        log.append("")

        # Validate
        v = validate_inputs(pitch_row, perm_pattern, duration_list)
        if not v["valid"]:
            for e in v["errors"]:
                log.append(f"ERROR: {e}")
            return json.dumps({"log": "\n".join(log), "files": {}, "error": True})
        for w in v["warnings"]:
            log.append(f"WARNING: {w}")

        # Stage 1
        log.append("--- Stage 1: Row Generation ---")
        s1 = run_stage1(pitch_row, perm_pattern, duration_list)
        log.append(f"Rhythm row: {' '.join(pc_name(p) for p in s1['rhythm_row'])}")
        log.append("")

        # Stage 2
        log.append("--- Stage 2: Zeitnetz V1 ---")
        s2 = run_stage2(s1)
        log.append(f"12 voices generated (144-element circular scan)")
        log.append("")

        # Stage 3
        log.append("--- Stage 3: Sound Families ---")
        s3_1, families = run_stage3(s1)
        n_families = len(families)
        log.append(f"Families: {n_families}")
        for rf in s3_1:
            log.append(f"  Row {rf['row_index']:2d}: "
                      f"{len(rf['pitches'])} families")
        log.append("")

        # Stage 4
        log.append("--- Stage 4: Full Score ---")
        s4 = run_stage4(s2, families)
        log.append(f"Bars: {s4['n_bars']}")
        log.append(f"Cycles: {s4['n_cycles']}")
        log.append(f"Staves: {s4['n_staves']}")
        log.append(f"All families done: {s4['all_done']}")
        log.append("")

        if not s4["all_done"]:
            log.append("WARNING: Not all families completed!")
            log.append("")

        # Build TS definitions (custom or default)
        active_ts_defs = TS_DEFS
        max_ts_type = 7

        if ts_types_mode == "custom" and ts_types_custom_str.strip():
            try:
                active_ts_defs, max_ts_type = build_custom_ts_defs(
                    ts_types_custom_str)
                ts_names = ", ".join(
                    f"{d['ts'][0]}/{d['ts'][1]}" for d in active_ts_defs.values())
                log.append(f"Custom TS types: {ts_names}")
                log.append(f"  ({max_ts_type} types defined)")
            except ValueError as e:
                log.append(f"ERROR parsing custom TS types: {e}")
                log.append("Falling back to default TS types.")
                active_ts_defs = TS_DEFS
                max_ts_type = 7
        else:
            log.append("Using default Lachenmann TS types (7 types)")

        # Time signature sequence
        if ts_mode == "auto":
            ts_seq = generate_auto_ts_sequence(s4["n_bars"])
            log.append(f"Auto TS sequence: {len(ts_seq)} entries")
        elif ts_mode == "custom" and ts_custom_str.strip():
            if ts_types_mode == "custom" and ts_types_custom_str.strip():
                ts_seq = parse_ts_sequence_custom(ts_custom_str, max_ts_type)
            else:
                ts_seq = parse_ts_sequence(ts_custom_str)
            log.append(f"Custom TS sequence: {len(ts_seq)} entries")
        else:
            ts_seq = DEFAULT_TS_SEQ
            log.append(f"Default TS sequence (105 Mouvement wedge)")
        log.append("")

        # Stage 5
        log.append("--- Stage 5: Final (Duration as Count) ---")
        s5 = run_stage5(s2, families, s4)
        log.append(f"Final bars: {s5['n_bars']}")
        log.append(f"Final staves: {s5['n_staves']}")
        log.append(f"Max grid position: {s5['max_grid_pos']}")
        log.append("")

        # Generate MusicXML files
        log.append("--- Generating MusicXML ---")

        log.append("  zeitnetz_stage4_score.musicxml ...")
        files["zeitnetz_stage4_score.musicxml"] = export_stage4_xml(s4)
        log.append("    Done.")

        log.append("  zeitnetz_v2.musicxml ...")
        files["zeitnetz_v2.musicxml"] = export_v2_xml(
            s4, ts_seq, ts_defs=active_ts_defs)
        log.append("    Done.")

        log.append("  zeitnetz_final.musicxml ...")
        files["zeitnetz_final.musicxml"] = export_final_xml(
            s5, ts_seq, ts_defs=active_ts_defs)
        log.append("    Done.")

        log.append("")
        log.append(f"=== Complete: {len(files)} files generated ===")

        return json.dumps({
            "log": "\n".join(log),
            "files": files,
            "error": False,
            "summary": {
                "n_families": n_families,
                "n_bars_s4": s4["n_bars"],
                "n_bars_final": s5["n_bars"],
                "n_staves_s4": s4["n_staves"],
                "n_staves_final": s5["n_staves"],
                "n_cycles": s4["n_cycles"],
            }
        })

    except Exception as e:
        log.append(f"\nERROR: {e}")
        import traceback
        log.append(traceback.format_exc())
        return json.dumps({"log": "\n".join(log), "files": {}, "error": True})


def api_validate(pitches_str, perm_str, durations_str):
    """Validate inputs and return results as JSON string."""
    log = []

    try:
        pitch_row = parse_pitch_input(pitches_str)
        perm_pattern = parse_int_list(perm_str, 12, "Permutation")
        duration_list = parse_int_list(durations_str, 13, "Durations")

        log.append("=== Input Validation ===")
        log.append(f"Pitch row:  {' '.join(pc_name(p) for p in pitch_row)}")
        log.append(f"Perm:       {perm_pattern}")
        log.append(f"Durations:  {duration_list}")
        log.append("")

        v = validate_inputs(pitch_row, perm_pattern, duration_list)
        for e in v["errors"]:
            log.append(f"ERROR: {e}")
        for w in v["warnings"]:
            log.append(f"WARNING: {w}")

        if v["valid"]:
            log.append("Syntax: OK")
            log.append("")
            log.append("--- Viability Test ---")
            vt = test_viability(pitch_row, perm_pattern, duration_list)
            log.append(vt["details"])

            if not vt["viable"]:
                log.append("")
                log.append("--- Repair Suggestions ---")
                repairs = suggest_repairs(pitch_row, perm_pattern, duration_list)
                if repairs:
                    for i, r in enumerate(repairs[:5]):
                        v2 = r["viability"]
                        log.append(
                            f"  {i+1}. {r['type']} (offset {r['offset']}): "
                            f"{v2['n_families']} families, "
                            f"{v2['n_cycles_needed']} cycles")
                        if r["type"] == "pitch_transposition":
                            row_str = " ".join(str(p) for p in r["pitch_row"])
                            log.append(f"     Pitches: {row_str}")
                        else:
                            dur_str = " ".join(str(d) for d in r["duration_list"])
                            log.append(f"     Durations: {dur_str}")
                else:
                    log.append("  No repairs found. Try Discovery mode.")
        else:
            log.append("Syntax: FAILED")

    except Exception as e:
        log.append(f"\nERROR: {e}")

    return json.dumps({"log": "\n".join(log)})


def api_discover(trials=100, seed=42, min_families=30):
    """Run discovery and return results as JSON string."""
    log = []
    log.append(f"=== Discovery Mode ===")
    log.append(f"Trials: {trials}, Seed: {seed}, Min families: {min_families}")
    log.append("")

    results, discover_log = discover(
        n_trials=trials, seed=seed if seed else None,
        min_families=min_families)

    log.append(discover_log)

    if results:
        log.append("")
        log.append("--- Top Results ---")
        for i, r in enumerate(results[:10]):
            log.append(
                f"\n  #{i+1}: {r['n_families']} families, "
                f"{r['n_cycles_needed']} cycles")
            log.append(
                f"    Pitches:   {' '.join(str(p) for p in r['pitch_row'])}")
            log.append(
                f"    Perm:      {' '.join(str(p) for p in r['perm_pattern'])}")
            log.append(
                f"    Durations: {' '.join(str(d) for d in r['duration_list'])}")

    return json.dumps({"log": "\n".join(log), "results": results})


def api_discover_by_families(target_families, tolerance=0, trials=500,
                             seed=None):
    """Run discovery targeting a specific family count.
    Returns JSON with results sorted by distance to target."""
    log = []
    log.append(f"=== Discovery by Family Count ===")
    log.append(f"Target: {target_families} families (+/- {tolerance})")
    log.append(f"Trials: {trials}, Seed: {seed}")
    log.append("")

    results, discover_log = discover_by_families(
        target_families=target_families,
        tolerance=tolerance,
        n_trials=trials,
        seed=seed if seed else None)

    log.append(discover_log)

    if results:
        log.append("")
        log.append("--- Matching Results ---")
        for i, r in enumerate(results[:20]):
            dist_str = ""
            if r["distance"] > 0:
                dist_str = f" (off by {r['distance']})"
            log.append(
                f"\n  #{i+1}: {r['n_families']} families{dist_str}, "
                f"{r['n_cycles_needed']} cycles")
            log.append(
                f"    Pitches:   {' '.join(str(p) for p in r['pitch_row'])}")
            log.append(
                f"    Perm:      {' '.join(str(p) for p in r['perm_pattern'])}")
            log.append(
                f"    Durations: {' '.join(str(d) for d in r['duration_list'])}")

    return json.dumps({"log": "\n".join(log), "results": results})
