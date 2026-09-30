"""The web console ships its own copy of the cross-language vector (its Docker build context is ./web,
so it cannot read ../tests). This guard fails if the copy drifts from the canonical file."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_vector_matches_canonical() -> None:
    canonical = (ROOT / "tests/vectors/manifest_vector.json").read_bytes()
    assert (ROOT / "web/test/fixtures/manifest_vector.json").read_bytes() == canonical, (
        "copy tests/vectors/manifest_vector.json to web/test/fixtures/"
    )
