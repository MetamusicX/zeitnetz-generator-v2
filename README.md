# Zeitnetz Generator v2

**Extended Edition — Custom Family Count Discovery and Custom Time Signatures**

An algorithmic time-grid generator for music composition, based on the serial procedures underlying Helmut Lachenmann's *Mouvement (– vor der Erstarrung)* (1982–84). This tool reconstructs and generalises the complete Zeitnetz (time-net) generation process as analysed by Pietro Cavalotti (2004) and Luís Antunes Pena (2004).

**Live app:** [lachenmann-machine-v2.netlify.app](https://lachenmann-machine-v2.netlify.app)

---

## What It Does

From three inputs — a 12-note pitch row, a permutation pattern, and a duration list — the generator produces a complete temporal scaffold for a musical composition:

- A 12×12 permutation matrix (pitch and rhythm rows)
- A variable number of **sound families** (typically 30–105), each defined by start and end pitch classes
- A multi-staff score of 300+ bars with the full time-grid
- Variable time signatures with proportional rhythmic notation
- A final duration-as-count transformation

All outputs are exported as **MusicXML** files, ready for import into Sibelius, Dorico, MuseScore, or Finale.

## What's New in v2

### 1. Discover by Family Count

The original generator's discovery mode finds viable input combinations and reports how many sound families each produces. Version 2 adds **targeted discovery**: specify the exact number of families you want (e.g., 52), and the system searches for input combinations that produce precisely that count.

- Set a target family count
- Optional tolerance range (e.g., ±2)
- Configurable number of search trials and random seed
- Results sorted by proximity to the target, each with a "Use" button to load its parameters

### 2. Custom Time Signature Types

The original generator uses Lachenmann's seven time signature types (3/8, 4/8, 3/4, 4/4, 3/2, 4/2, 12/4), each mapping 12 grid positions per bar at different proportional scales. Version 2 allows the user to define **any set of time signatures**.

- Enter time signatures in plain notation: `3/8, 5/8, 7/8, 3/4, 4/4, 12/4`
- Each time signature is automatically analysed for optimal beat grouping
- The system distributes 12 grid positions across beats, **minimising tuplet complexity**
- Clean divisions (e.g., 3 or 6 beats) produce no tuplets; irregular divisions (e.g., 5 or 7 beats) use the simplest possible tuplet notation
- The cyclic time signature sequence then references your custom types by index

This enables Ferneyhough-style irregular metres, asymmetric bar structures, and experimental time-signature schemes — all while preserving the 12-position grid logic of the Zeitnetz.

## How It Works

The tool runs **entirely in the browser** — no server-side computation. The Python engine executes via [Pyodide](https://pyodide.org/) (CPython compiled to WebAssembly). MusicXML files are generated client-side and downloaded directly.

### The Five-Stage Pipeline

1. **Row Generation** — Builds a 12×12 permutation matrix from the pitch row and permutation pattern. Derives the rhythm row via onset addresses computed from the duration list.

2. **Zeitnetz Version 1 (Circular Reading)** — Concatenates all permutations into tapes and performs a circular forward scan to derive durations. Produces 12 rows of 12 notes in 3/8 time.

3. **Sound Families (Klangfamilien)** — Reads the permutation rows in a specific circular order to extract family start pitches. End pitches are derived by a symmetrical mirror reading. The number of families depends on the specific inputs.

4. **Full Score** — Cyclically extends the Zeitnetz until all families have activated and deactivated. Produces a multi-staff score with the Zeitnetz on the top staff and families distributed below.

5. **Variable Time Signatures and Duration as Count** — Applies the cyclic time-signature sequence (default or custom) and reinterprets duration values as event counts, spreading families across the full time-grid.

### Validation and Discovery

Not all input combinations produce a functioning Zeitnetz. The estimated probability of a random input working is approximately **1 in 18,500**. The tool provides:

- **Validate** — Tests whether your inputs will produce a functioning pipeline before generating
- **Discover** — Searches for viable random input combinations using a smart algorithm that guarantees collision-free duration lists
- **Discover by Family Count** *(new in v2)* — Searches specifically for inputs producing a target number of families

## Inputs

| Parameter | Format | Default (Lachenmann's *Mouvement*) |
|---|---|---|
| **Pitch row** | 12 integers (0–11) or German names (c cis d dis e f fis g gis a ais h) | 1 11 0 8 9 3 6 4 2 10 5 7 |
| **Permutation** | 12 integers (0–11), each appearing once | 1 5 0 6 2 7 11 8 3 10 4 9 |
| **Durations** | 13 integers; first may be negative (initial rest) | -11 6 9 7 6 6 4 3 10 6 3 1 10 |
| **Time signatures** *(v2)* | Comma-separated time signatures, e.g. `3/8, 5/8, 7/8, 3/4` | Default: 7 Lachenmann types |

## Outputs

| File | Description |
|---|---|
| `zeitnetz_stage4_score.musicxml` | Full score in uniform 3/8 |
| `zeitnetz_v2.musicxml` | Full score with variable time signatures |
| `zeitnetz_final.musicxml` | Duration-as-count transformation |

## Running Locally

No installation required — open `index.html` in a modern browser (Chrome, Firefox, Safari, Edge). The app fetches the Pyodide runtime (~20 MB) from CDN on first load.

For local development, serve the files with any static server:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

## Related Projects

- [Lachenmann Machine — Zeitnetz Generator v1](https://github.com/MetamusicX/zeitnetz-generator) — Original generalised generator
- [Lachenmann Machine — Pipeline](https://github.com/MetamusicX/Lachenmann-machine_zeitnetz-generator) — Mouvement-specific Python pipeline
- **v1 web app:** [lachenmann-machine-zeitnetz-generator.netlify.app](https://lachenmann-machine-zeitnetz-generator.netlify.app)

## Context

This tool was developed as part of the ERC Advanced Grant *Posthuman Music: Creative Practices after AI* (2026–2030) at the Orpheus Institute, Ghent. It is the first in a series of "compositional machines" — computational reconstructions of the algorithmic engines underlying major works of post-serial composition.

## Author

**Paulo de Assis**
Orpheus Institute, Ghent

## License

MIT
