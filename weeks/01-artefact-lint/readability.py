#!/usr/bin/env python3
"""
Plain English readability check for /sharpen output.

Deterministic — computes the same score every run, so the number is a real,
comparable metric, not an LLM estimate. Reads the rewrite from a file arg or
stdin, strips markdown formatting, and scores the prose against plain-English
thresholds for business comms.

Usage:
    python3 readability.py < rewrite.txt
    python3 readability.py rewrite.txt
    echo "some text" | python3 readability.py --json

Exit code: 0 = PASS, 1 = REVISE (a threshold failed). Always prints the scorecard.
"""

import sys
import re
import json

# Terms the plain-English / hype / management-speak rules forbid. Any hit = hard fail.
FLAGGED = [
    # Latinate / formal (swap-list)
    "utilise", "utilize", "utilisation", "leverage", "commence", "initiate",
    "terminate", "cease", "facilitate", "demonstrate", "regarding",
    "sufficient", "approximately", "subsequently", "numerous", "endeavour",
    "ascertain", "operationalise", "operationalize", "prior to", "in order to",
    "with respect to", "in relation to",
    # hype
    "game-changer", "game changer", "supercharge", "skyrocket", "turbocharge",
    "seamless", "revolutionise", "revolutionize", "unlock",
    # management-speak / clichés
    "synergy", "bandwidth", "touch base", "deep dive", "double-click",
    "circle back", "low-hanging fruit", "moving the needle", "north star",
    "at the end of the day",
]

PASSIVE_RE = re.compile(
    r"\b(am|is|are|was|were|be|been|being)\b\s+(\w+ed|done|made|shown|sent|"
    r"built|given|taken|seen|held|flagged|raised|driven|run)\b",
    re.IGNORECASE,
)

THRESHOLDS = {
    "fk_grade_max": 12.0,      # Flesch-Kincaid grade — target plain business prose
    "avg_sentence_max": 18.0,  # words per sentence
    "longest_sentence_max": 25,  # hard cap, matches rubric item 5
    "flagged_max": 0,          # zero formal/hype/jargon terms
    "passive_max": 1,          # at most one passive construction
}


def strip_markdown(text: str) -> str:
    text = re.sub(r"`[^`]*`", " ", text)          # inline code
    text = re.sub(r"[*_>#|]", " ", text)           # bold/italic/quote/head/table
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> label
    text = re.sub(r"^\s*[-*+]\s+", " ", text, flags=re.MULTILINE)  # bullet markers
    return text


def syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith("le") and count > 1:
        count -= 1
    return max(1, count)


def split_sentences(text: str):
    # Each bullet/line is its own sentence for comms; then split on . ! ?
    text = strip_markdown(text)
    text = re.sub(r"\n+", " . ", text)
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def analyse(text: str) -> dict:
    sentences = split_sentences(text)
    words = re.findall(r"[A-Za-z']+", strip_markdown(text))
    n_words = len(words)
    n_sentences = max(1, len(sentences))
    n_syll = sum(syllables(w) for w in words)

    sentence_lengths = [len(re.findall(r"[A-Za-z']+", s)) for s in sentences]
    longest = max(sentence_lengths) if sentence_lengths else 0
    avg_sentence = n_words / n_sentences

    if n_words:
        fk_grade = 0.39 * (n_words / n_sentences) + 11.8 * (n_syll / n_words) - 15.59
        fre = 206.835 - 1.015 * (n_words / n_sentences) - 84.6 * (n_syll / n_words)
    else:
        fk_grade, fre = 0.0, 100.0

    low = text.lower()
    flagged_hits = sorted({t for t in FLAGGED if re.search(r"\b" + re.escape(t) + r"\b", low)})
    passive_hits = len(PASSIVE_RE.findall(text))

    checks = {
        "fk_grade": (round(fk_grade, 1), fk_grade <= THRESHOLDS["fk_grade_max"]),
        "avg_sentence_len": (round(avg_sentence, 1), avg_sentence <= THRESHOLDS["avg_sentence_max"]),
        "longest_sentence": (longest, longest <= THRESHOLDS["longest_sentence_max"]),
        "flagged_terms": (flagged_hits, len(flagged_hits) <= THRESHOLDS["flagged_max"]),
        "passive_count": (passive_hits, passive_hits <= THRESHOLDS["passive_max"]),
    }
    verdict = "PASS" if all(ok for _, ok in checks.values()) else "REVISE"

    return {
        "words": n_words,
        "sentences": n_sentences,
        "flesch_reading_ease": round(fre, 1),
        "checks": checks,
        "verdict": verdict,
    }


def render(r: dict) -> str:
    def mark(ok):
        return "PASS" if ok else "FAIL"
    c = r["checks"]
    lines = [
        f"Plain English check: {r['verdict']}  "
        f"(Flesch Reading Ease {r['flesch_reading_ease']}, {r['words']}w / {r['sentences']} sentences)",
        f"  - FK grade {c['fk_grade'][0]} (≤{THRESHOLDS['fk_grade_max']})            [{mark(c['fk_grade'][1])}]",
        f"  - avg sentence {c['avg_sentence_len'][0]}w (≤{THRESHOLDS['avg_sentence_max']})       [{mark(c['avg_sentence_len'][1])}]",
        f"  - longest sentence {c['longest_sentence'][0]}w (≤{THRESHOLDS['longest_sentence_max']})    [{mark(c['longest_sentence'][1])}]",
        f"  - flagged terms {c['flagged_terms'][0] or 'none'} (=0)        [{mark(c['flagged_terms'][1])}]",
        f"  - passive voice {c['passive_count'][0]} (≤{THRESHOLDS['passive_max']})            [{mark(c['passive_count'][1])}]",
    ]
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    if args:
        with open(args[0], "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    result = analyse(text)
    print(json.dumps(result) if as_json else render(result))
    sys.exit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
