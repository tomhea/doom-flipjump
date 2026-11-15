"""The README's and the story's numbers for the shipped build are the measured ones: the chart's shares come from the
classifier's output and the build's time and RAM from the timed rebuild's log (docs/ship-evidence; ship-gate.md 15)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "ship-evidence"
GAME = ("Game logic", "Status bar and menus")


def prose(relative):
    """a document's text on one line (a caption wraps where its editor wrapped it)"""
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


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


def millions(parts):
    return "%.1fM" % (sum(parts.values()) / 1e6)


def rebuild():
    """the timed rebuild: rss_run.py's record, the last line of the build's log"""
    last = (EVIDENCE / "blocked65_remeasure_build.log").read_text(encoding="ascii").splitlines()[-1]
    assert last.startswith("RSS_RUN "), last[:40]
    return json.loads(last[len("RSS_RUN "):])


def build_minutes():
    return "about %d minutes" % round(rebuild()["seconds"] / 60)


def build_ram():
    return "about %d GB of RAM" % round(rebuild()["peak_tree_private_gb"])


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
    ops, words = millions(frame_ops()), millions(program_words())
    assert "where the %s flip-jumps of a mean frame go, and what the %s-word program is made of" % (ops, words) \
        in prose("README.md")
    story = prose("docs/story.md")
    assert "the %s flip-jumps of a mean frame" % ops in story
    assert "the %s-word program" % words in story


def test_both_documents_say_the_chart_is_the_shipped_builds():
    assert "Measured on the shipped build, blocked65." in prose("README.md")
    assert "Measured on the shipped build, blocked65." in prose("docs/story.md")


def test_each_document_shows_a_chart_that_is_in_the_repo():
    for relative, media in (("README.md", ROOT), ("docs/story.md", ROOT / "docs")):
        pictures = re.findall(r"[\w/]*_pies\.png", prose(relative))
        assert pictures == [pictures[0]], (relative, pictures)
        assert (media / pictures[0]).is_file(), (relative, pictures[0])
        assert pictures[0].endswith("media/blocked65_pies.png"), (relative, pictures[0])


def test_the_build_time_and_ram_are_the_timed_rebuilds():
    readme = prose("README.md")
    assert readme.count(build_minutes()) == 3, build_minutes()
    assert readme.count(build_ram()) == 2, build_ram()
    assert build_ram() in prose("docs/developing.md")
    assert not re.search(r"about \d+ minutes", readme.replace(build_minutes(), ""))
    assert not re.search(r"\d+ GB of RAM", readme.replace(build_ram(), ""))
