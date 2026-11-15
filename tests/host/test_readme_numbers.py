"""The README's, the story's and the developing guide's numbers for the shipped build are the measured ones: the
chart's shares come from the classifier's output, the build's time and RAM from the timed rebuild's log, and the timed
rebuild is the shipped binary by its hash (docs/ship-evidence; ship-gate.md 15)."""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "ship-evidence"
GAME = ("Game logic", "Status bar and menus")


def prose(relative):
    """a document's text on one line (a caption wraps where its editor wrapped it)"""
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


def evidence_lines(name):
    return (EVIDENCE / name).read_text(encoding="ascii").splitlines()


def classified():
    return json.loads((EVIDENCE / "blocked65_pies_classified.json").read_text(encoding="ascii"))


def frame_ops():
    """category -> ops of a mean frame"""
    return classified()["ops"]


def program_words():
    """category -> words of the program: its own and its share of the word-flip chains"""
    return {category: own + chains for category, (own, chains) in classified()["size"].items()}


def percent(parts, *categories):
    return 100 * sum(parts[category] for category in categories) / sum(parts.values())


def millions(parts, digits=1):
    return "%.*fM" % (digits, sum(parts.values()) / 1e6)


def rebuild():
    """the timed rebuild: rss_run.py's record, the last line of the build's log"""
    last = evidence_lines("blocked65_remeasure_build.log")[-1]
    assert last.startswith("RSS_RUN "), last[:40]
    return json.loads(last[len("RSS_RUN "):])


def build_minutes():
    return "about %d minutes" % round(rebuild()["seconds"] / 60)


def build_ram():
    return "about %d GB of RAM" % round(rebuild()["peak_tree_private_gb"])


def shipped_sha256():
    """E1M1's recorded hash, from the episode creator's registry"""
    spec = importlib.util.spec_from_file_location("build_episode", ROOT / "scripts" / "build_episode.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_episode", module)        # dataclasses resolve the module by name
    spec.loader.exec_module(module)
    return module.REGISTRY["E1M1"].recorded_sha256


def test_the_readme_caption_carries_the_measured_shares():
    ops, words, readme = frame_ops(), program_words(), prose("README.md")
    assert ("Drawing walls is %.0f%% of it and sprites %.0f%%; all the game logic, the status bar and the menus "
            "together are %.1f%%." % (percent(ops, "Walls"), percent(ops, "Sprites"), percent(ops, *GAME))) in readme
    assert "Lookup tables are %.0f%% of it" % percent(words, "Lookup tables") in readme


def test_the_story_caption_carries_the_measured_shares():
    ops, words, story = frame_ops(), program_words(), prose("docs/story.md")
    assert ("Walls take %.0f%%, sprites %.0f%%, floors and ceilings %.1f%%, the BSP walk %.1f%%; all the game logic, "
            "the status bar and the menus together are %.1f%%."
            % (percent(ops, "Walls"), percent(ops, "Sprites"), percent(ops, "Floors and ceilings"),
               percent(ops, "BSP walk"), percent(ops, *GAME))) in story
    assert "Lookup tables are %.0f%% of it" % percent(words, "Lookup tables") in story


def test_both_captions_carry_the_measured_totals():
    ops, words = frame_ops(), program_words()
    assert ("where the %s flip-jumps of a mean frame go, and what the %s-word program is made of"
            % (millions(ops), millions(words))) in prose("README.md")
    story = prose("docs/story.md")
    assert "what the %s-word program is made of" % millions(words, digits=0) in story
    assert "the %s flip-jumps of a mean frame" % millions(ops) in story
    assert "the %s-word program" % millions(words) in story


def test_the_measured_build_is_the_shipped_binary():
    assert "sha256 " + shipped_sha256() in evidence_lines("blocked65_remeasure_chain.log")
    for relative in ("README.md", "docs/story.md"):
        assert "Measured on the shipped build, blocked65." in prose(relative), relative


def test_each_document_shows_a_chart_that_is_in_the_repo():
    for relative, media in (("README.md", ROOT), ("docs/story.md", ROOT / "docs")):
        pictures = re.findall(r"[\w/]*_pies\.png", prose(relative))
        assert pictures == [pictures[0]], (relative, pictures)
        assert (media / pictures[0]).is_file(), (relative, pictures[0])
        assert pictures[0].endswith("media/blocked65_pies.png"), (relative, pictures[0])


def test_every_build_time_and_ram_is_the_timed_rebuilds():
    readme, developing = prose("README.md"), prose("docs/developing.md")
    assert set(re.findall(r"about \d+ minutes", readme)) == {build_minutes()}
    assert set(re.findall(r"about \d+ GB of RAM", readme)) == {build_ram()}
    assert set(re.findall(r"\d+ GB of RAM", readme + developing)) == {build_ram()[len("about "):]}
