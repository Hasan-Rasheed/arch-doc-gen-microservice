"""Where the sample drawings live: the project's Samples/ folder, one folder per project
("Gegmebi - Sample 3", "Ardstudio LLC - Sample 2", …). Finished albums sit next to their inputs
with "output" in the file name; everything else is an input drawing."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "Samples"
GEGMEBI = SAMPLES / "Gegmebi - Sample 3" / "gegmebi input.pdf"
# The architects' album for GEGMEBI (one revision later) — the answer key.
GEGMEBI_ALBUM = SAMPLES / "Gegmebi - Sample 3" / "gegmebi output.pdf"
# Single pages cut from the Bochorma №11 album (Sample 1/Output.pdf), e.g. "42 Grand Master.pdf".
BOCHORMA_PAGES = SAMPLES / "Sample 1"
# One hotel floor, layered, from the client (rooms named "სასტუმროს ნომერი … Room").
HOTEL = SAMPLES / "samushao - Sample 6" / "samushao nazaxi msheneblebistvis_ 25.08.2026 1.pdf"


def is_album(path: Path) -> bool:
    return "output" in path.name.lower()


def project(path: Path, samples: Path = SAMPLES) -> str:
    """The sample folder a file belongs to."""
    rel = path.relative_to(samples)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def inputs(samples: Path = SAMPLES) -> list[Path]:
    """Every input drawing (albums left out)."""
    return [p for p in sorted(samples.rglob("*.pdf")) if not is_album(p)]
