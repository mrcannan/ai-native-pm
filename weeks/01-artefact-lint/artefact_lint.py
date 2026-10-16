#!/usr/bin/env python3
"""
artefact-lint — a linter for human-facing PM artefacts (PRDs, roadmaps, one-pagers,
briefs, status updates).

The bar:       outputs must be actionable without further interpretation.
The principle: AI should be saving the team time, not just saving you time.
The test:      if the reader has to re-run AI to decode it, the artefact failed.

Scope: HUMAN-FACING PM artefacts only. It deliberately does NOT bind data analysis,
dashboards, SQL, notebooks or code. The defect this catches is editing discipline in
documents, not AI use in general.

Checks:
  B  story-brief    no `story:` brief (audience / outcome / impact / key_info) answered
                    before drafting; >5 key facts; opening that never states the outcome
  G  genre-mix      roadmap carrying risks/decisions/findings; PRD carrying solution design
  D  dates          in-flight items with no date (committed / "(est.)" / TBC-with-when)
  S  structure      prose lines outnumbering table rows + dated items in a plan artefact
  W  word budget    per-genre length budget (a roadmap over budget is an essay)
  O  opening        artefact opens with prose instead of the ask / the dated table
  A  ai-texture     AI tells: flagged terms (from readability.py), em-dash density in
                    prose, long sentences, bullet runs
  K  key-info       with --body-file: every key_info item survived into the SENT text

Usage:
  python3 artefact_lint.py <file> [--json] [--genre GENRE]
  cat draft.md | python3 artefact_lint.py --stdin --path <path> [--json]
  python3 artefact_lint.py <draft.md> --body-file <sent.txt>
  python3 artefact_lint.py --selftest
  python3 artefact_lint.py --triggers <path>    # exit 0 if path is in scope

Config: artefact-craft.json next to this file (override with ARTEFACT_LINT_CONFIG).
Scope globs are matched against the path relative to the current working directory.

Exit codes: 0 = PASS (or out of scope), 2 = findings, 1 = usage/IO error.
Degradation is explicit: if a sensor is unavailable (config missing, readability.py
unimportable) the report SAYS SO and the affected check reports UNAVAILABLE — never PASS.
"""

import sys
import os
import re
import json
import fnmatch
import argparse
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.getcwd()  # scope globs are relative to where you run it
CONFIG_PATH = os.environ.get("ARTEFACT_LINT_CONFIG") or os.path.join(HERE, "artefact-craft.json")
READABILITY_PATH = os.path.join(HERE, "readability.py")

# Document-shape AI tells. Distinct concern from readability.py's FLAGGED list, which owns
# plain-English word choice; these are structural/rhetorical tells that show up in documents.
ARTEFACT_TELLS = [
    "it's worth noting", "it is worth noting", "in summary", "to summarise",
    "to summarize", "to recap", "as mentioned above", "as outlined below",
    "as previously discussed", "delve", "it's important to note",
    "it is important to note", "that being said", "navigating the complexities",
    "in today's", "ever-evolving", "a testament to", "plays a vital role",
    "plays a crucial role", "comprehensive overview", "holistic approach",
]
CHAIN_WORDS = ["furthermore", "moreover", "additionally"]

DEFAULT_THRESHOLDS = {
    "word_budget": {"roadmap": 900, "prd": 2500, "one-pager": 700,
                    "brief": 1200, "status": 500, "generic": 3000},
    "emdash_per_1000_prose_words": 22,
    "max_bullet_run": 6,
    "max_sentence_words": 30,
    "opening_prose_lines_max": 5,
}

DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}"                       # 2026-09-21
    r"|\b(Q[1-4])\b"                            # Q1
    r"|\bFY\d{2}\b"                             # FY27
    r"|\bW\d{1,2}\b"                            # W39
    r"|\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\s+\d{1,2}"
    r"|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r"|\bH[12]\b"                               # H1/H2 (half)
    r"|\(est\.?\)"                              # (est.)
    r"|\bTBC\b|\bTBD\b"                         # explicit unknown
    r"|\bEOD\b|\bEOW\b"
    r")"
)


# Story brief — the four questions answered BEFORE drafting (the story brief). The linter checks the answers exist and that the draft honours them.
STORY_FIELDS = ("audience", "outcome", "impact", "key_info")
STORY_PLACEHOLDERS = {"", "?", "tbc", "tbd", "todo", "[fill]", "-"}
STORY_MAX_KEY_INFO = 5
STORY_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "their", "they",
    "them", "what", "want", "will", "have", "about", "before", "after", "should",
    "would", "could", "your", "our", "get", "make", "agree", "able",
}


# ---------------------------------------------------------------- loading

def load_config():
    """Returns (config, note). note is non-empty when a sensor is degraded."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f), ""
    except Exception as e:
        return None, f"config UNAVAILABLE at {CONFIG_PATH}: {e}"


def load_readability():
    """Import the sibling readability.py. One implementation of the plain-English list."""
    try:
        spec = importlib.util.spec_from_file_location("readability", READABILITY_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, ""
    except Exception as e:
        return None, f"readability.py UNAVAILABLE at {READABILITY_PATH}: {e}"


# ---------------------------------------------------------------- scoping

def _norm(path):
    p = path if not os.path.isabs(path) and not os.path.exists(path) else os.path.abspath(path)
    try:
        rel = os.path.relpath(p, REPO)
        if not rel.startswith(".."):
            p = rel
    except Exception:
        pass
    return p.replace(os.sep, "/")


def in_scope(path, config):
    """True if this path is a human-facing PM artefact the bar binds."""
    if config is None:
        return False, "config unavailable — scope undecidable"
    rel = _norm(path)
    for g in config.get("exempt_globs", []):
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, g):
            return False, f"exempt: {g}"
    for g in config.get("trigger_globs", []):
        if fnmatch.fnmatch(rel, g):
            return True, f"trigger: {g}"
    return False, "no trigger glob matched"


def detect_genre(path, text, override=None):
    if override:
        return override
    rel = _norm(path).lower()
    m = re.search(r"^type:\s*(.+)$", text, re.MULTILINE)
    hint = (m.group(1).strip().lower() if m else "") + " " + rel
    for genre, keys in [
        ("roadmap", ["roadmap"]),
        ("prd", ["prd", "product requirements"]),
        ("one-pager", ["one-pager", "onepager", "one pager"]),
        ("brief", ["brief"]),
        ("status", ["status", "update", "weekly"]),
    ]:
        if any(k in hint for k in keys):
            return genre
    return "generic"


# ---------------------------------------------------------------- parsing

def classify_lines(text):
    """Split into (prose, bullet, table, heading, other) keeping 1-indexed line numbers."""
    out = {"prose": [], "bullet": [], "table": [], "heading": [], "other": []}
    in_fm = False
    in_code = False
    in_comment = False
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        s = line.strip()
        if in_comment:
            out["other"].append((i, line))
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--") and not in_code:
            out["other"].append((i, line))
            in_comment = "-->" not in s
            continue
        if i == 1 and s == "---":
            in_fm = True
            out["other"].append((i, line)); continue
        if in_fm:
            out["other"].append((i, line))
            if s == "---":
                in_fm = False
            continue
        if s.startswith("```"):
            in_code = not in_code
            out["other"].append((i, line)); continue
        if in_code or not s:
            out["other"].append((i, line)); continue
        if s.startswith("#"):
            out["heading"].append((i, line))
        elif s.startswith("|"):
            out["table"].append((i, line))
        elif re.match(r"^([-*+]|\d+\.)\s+", s):
            out["bullet"].append((i, line))
        elif s.startswith(">"):
            out["other"].append((i, line))
        else:
            out["prose"].append((i, line))
    return out


def words_of(lines):
    return sum(len(re.findall(r"[A-Za-z'£$%\d]+", l)) for _, l in lines)


# ---------------------------------------------------------------- story brief

def parse_story(text):
    """Return {field: [values]} from the `story:` frontmatter block or a `<!-- story` comment.

    None means NO brief was found — distinct from a brief with empty fields, which
    returns the dict with those fields empty so the check can name them.
    """
    raw = text.splitlines()
    block = None
    if raw and raw[0].strip() == "---":
        fm = []
        for l in raw[1:]:
            if l.strip() == "---":
                break
            fm.append(l)
        for i, l in enumerate(fm):
            if re.match(r"^story:\s*$", l):
                block = []
                for m in fm[i + 1:]:
                    if m.strip() and not m.startswith((" ", "\t")):
                        break
                    block.append(m)
                break
    if block is None:
        m = re.search(r"<!--\s*story:?[ \t]*\n(.*?)-->", text, re.S)
        if m:
            block = m.group(1).splitlines()
    if block is None:
        return None

    fields = {f: [] for f in STORY_FIELDS}
    cur = None
    for l in block:
        s = l.strip()
        if not s:
            continue
        km = re.match(r"^([a-z_]+):\s*(.*)$", s)
        if km and km.group(1) in STORY_FIELDS:
            cur = km.group(1)
            val = km.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                # split on commas, but not the thousands comma inside "25,700" (2026-10-16)
                fields[cur] += [v.strip() for v in re.split(r",(?!\d{3}(?!\d))", val[1:-1])]
            elif val:
                fields[cur].append(val)
        elif s.startswith("- ") and cur:
            fields[cur].append(s[2:].strip())
    for f in STORY_FIELDS:
        fields[f] = [v.strip("\"' ") for v in fields[f]
                     if v.strip("\"' ").lower() not in STORY_PLACEHOLDERS]
    return fields


def _stems(text):
    words = re.findall(r"[a-z][a-z0-9'-]+", text.lower())
    return {w[:4] if len(w) <= 6 else w[:5]
            for w in words if len(w) >= 4 and w not in STORY_STOPWORDS}


def check_story(text, lines):
    story = parse_story(text)
    if story is None:
        return [("B", "No story brief. Answer these four in frontmatter `story:` before "
                      "drafting: audience (who reads it, and how it reaches them), "
                      "outcome (what you want to happen), impact (who or what it "
                      "affects), key_info (the ≤5 facts that matter).", "MUST")]
    missing = [f for f in STORY_FIELDS if not story[f]]
    if missing:
        return [("B", f"Story brief incomplete: {', '.join(missing)} unanswered. If you "
                      f"can't answer it, the artefact isn't ready to draft.", "MUST")]
    findings = []
    n = len(story["key_info"])
    if n > STORY_MAX_KEY_INFO:
        findings.append(("B", f"key_info lists {n} items (cap {STORY_MAX_KEY_INFO}). If "
                              f"everything is key, nothing is: cut or move to a linked doc.",
                         "TRIM"))
    body = sorted(lines["prose"] + lines["bullet"] + lines["table"] + lines["heading"],
                  key=lambda t: t[0])[:15]
    want = _stems(" ".join(story["outcome"]))
    have = _stems(" ".join(l for _, l in body))
    if want and not (want & have):
        findings.append(("B", f"Opening never states the outcome ('{story['outcome'][0][:70]}'). "
                              f"Put the ask in the first lines.", "TRIM"))
    return findings


ANCHOR_RX = re.compile(
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+20\d\d)?"
    r"|20\d\d-\d\d-\d\d"
    r"|£\s?[\d,.]+\s?[kmbn]?\b"
    r"|[\d,.]+\s?%"
    r"|\b\d+(?:\.\d+)?\s?(?:pp|bps|k|m|x|wks?|weeks?|days?|months?)\b"
    r"|\b\d[\d,]{2,}\b", re.I)


def _anchors(s):
    return [a.strip() for a in ANCHOR_RX.findall(s)]


def _squash(s):
    return re.sub(r"[\s,]", "", s.lower())


def check_key_info_survival(story, body_text):
    """Every key_info item must survive into the body: its dates and numbers verbatim, or, when
    it carries none, at least half its content words. A real send once shipped 2 of
    its 5 key_info items; the other three never left the draft."""
    if not story or not story.get("key_info"):
        return []
    body = _squash(body_text)
    have = _stems(body_text)
    findings = []
    for item in story["key_info"]:
        anchors = _anchors(item)
        if anchors:
            missing = [a for a in anchors if _squash(a) not in body]
            if missing:
                findings.append(("K", f"key_info '{item[:60]}': {', '.join(missing)} not in the body. "
                                      f"A fact in the brief that never reaches the reader was not "
                                      f"sent.", "MUST"))
            continue
        want = _stems(item)
        if want and len(want & have) < max(1, len(want) // 2):
            findings.append(("K", f"key_info '{item[:60]}' does not appear in the body.", "TRIM"))
    return findings


# ---------------------------------------------------------------- checks

def check_genre_mix(genre, lines, config):
    rules = (config or {}).get("genre_mix", {})
    rule = rules.get(genre)
    if not rule:
        return []
    pat = re.compile(rule["forbidden_section_pattern"])
    hits = [(n, l.strip()) for n, l in lines["heading"] if pat.search(l)]
    if not hits:
        return []
    shown = "; ".join(f"L{n} {t[:60]}" for n, t in hits[:5])
    extra = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
    return [("G", f"{rule['message']} Sections: {shown}{extra}", "MUST")]


def check_dates(genre, lines):
    if genre not in ("roadmap", "status"):
        return []
    candidates = [(n, l) for n, l in lines["bullet"] + lines["table"]
                  if len(l.strip()) > 20 and not re.match(r"^\s*\|[\s\-:|]+\|?\s*$", l)]
    if not candidates:
        return []
    undated = [(n, l.strip()) for n, l in candidates if not DATE_RE.search(l)]
    if not undated:
        return []
    ratio = len(undated) / len(candidates)
    if ratio < 0.34:
        return []
    shown = "; ".join(f"L{n}" for n, _ in undated[:6])
    return [("D", f"{len(undated)}/{len(candidates)} in-flight items carry no date "
                  f"({shown}). Every in-flight item needs a date — committed, "
                  f"'(est.)', or when the firm date gets confirmed.", "MUST")]


def check_structure(genre, lines):
    if genre not in ("roadmap", "status"):
        return []
    prose_w = words_of(lines["prose"])
    struct_w = words_of(lines["table"]) + words_of(lines["bullet"])
    if prose_w <= struct_w or prose_w < 120:
        return []
    return [("S", f"Reads as an essay, not a plan: {prose_w} words of prose vs "
                  f"{struct_w} in tables/lists. A rough timeline with dates "
                  f"beats an essay.", "MUST")]


def check_budget(genre, lines, thresholds):
    budgets = thresholds.get("word_budget", {})
    budget = budgets.get(genre, budgets.get("generic", 3500))
    hard = thresholds.get("word_budget_hard_multiple", 2.0)
    total = sum(words_of(v) for k, v in lines.items() if k != "other")
    if total <= budget:
        return []
    sev = "MUST" if total > budget * hard else "TRIM"
    tail = (" Past twice the budget this is an essay, not an artefact."
            if sev == "MUST" else "")
    return [("W", f"{total} words against a {budget}-word budget for a {genre}.{tail}", sev)]


ACTIONABLE_LEAD = re.compile(
    r"(?i)\*\*\s*(ask|decision|recommendation|one line|one-line|bottom line|tl;?dr|"
    r"deliverable|verdict|status|headline|what (we|i) need|next step|summary)\b"
    r"|^\s*>\s*\*\*"
)


def check_opening(lines, thresholds):
    """Fires only when the top of the artefact offers the reader nothing to act on.

    A short lead paragraph is legitimate. The defect is an artefact whose
    opening is prose with no ask, no decision, no dated item and no table in sight.
    All three escape hatches must be absent before this flags.
    """
    body = sorted(lines["prose"] + lines["bullet"] + lines["table"] + lines["heading"],
                  key=lambda t: t[0])
    body = [b for b in body if not re.match(r"^\s*#\s", b[1])]
    if not body:
        return []
    window = body[:25]
    prose_nums = {n for n, _ in lines["prose"]}
    struct_nums = {n for n, _ in lines["table"] + lines["bullet"]}

    prose_run = 0
    for n, _ in body[:12]:
        if n in struct_nums:
            break
        if n in prose_nums:
            prose_run += 1

    limit = thresholds.get("opening_prose_lines_max", 5)
    if prose_run <= limit:
        return []
    win_text = "\n".join(l for _, l in window)
    if ACTIONABLE_LEAD.search(win_text):
        return []
    if any(n in struct_nums and DATE_RE.search(l) for n, l in window):
        return []
    if any(n in struct_nums for n, _ in window[:10]):
        return []
    return [("O", f"Opens with {prose_run} lines of prose and nothing actionable in the "
                  f"first 25 lines — no ask, no decision, no dated item, no table. "
                  f"Lead with what the reader has to do.", "MUST")]


def check_ai_texture(lines, thresholds, readability):
    findings = []
    prose_lines = lines["prose"]
    prose_text = "\n".join(l for _, l in prose_lines)
    all_text = "\n".join(l for _, l in sorted(
        sum([v for k, v in lines.items() if k != "other"], []), key=lambda t: t[0]))
    low = all_text.lower()

    tells = sorted({t for t in ARTEFACT_TELLS if t in low})
    if tells:
        findings.append(("A", f"AI tells present: {', '.join(tells[:6])}. Strip them.", "MUST"))

    chains = [w for w in CHAIN_WORDS if re.search(r"\b" + w + r"\b", low)]
    if len(chains) >= 2 or any(low.count(w) >= 2 for w in CHAIN_WORDS):
        findings.append(("A", f"Enumeration chain ({', '.join(chains)}) reads as generated. "
                              f"Use 'Also', or make it a list.", "MUST"))

    pw = words_of(prose_lines)
    if pw >= 100:
        em = prose_text.count("—")
        density = em * 1000.0 / pw
        limit = thresholds.get("emdash_per_1000_prose_words", 12)
        if density > limit:
            findings.append(("A", f"Em-dash density {density:.0f} per 1000 prose words "
                                  f"(limit {limit}, {em} in {pw} words). The single "
                                  f"loudest AI tell — replace with colons or full stops.", "MUST"))

    maxw = thresholds.get("max_sentence_words", 30)
    longs = []
    for n, l in prose_lines:
        for sent in re.split(r"(?<=[.!?])\s+|\s+\u00b7\s+", l):
            wc = len(re.findall(r"[A-Za-z']+", sent))
            if wc > maxw:
                longs.append((n, wc))
    if longs:
        shown = "; ".join(f"L{n} ({w}w)" for n, w in longs[:5])
        findings.append(("A", f"{len(longs)} sentence(s) over {maxw} words: {shown}. Split them.", "TRIM"))

    run = best = 0
    prev = None
    for n, _ in sorted(lines["bullet"]):
        run = run + 1 if prev is not None and n == prev + 1 else 1
        best = max(best, run)
        prev = n
    cap = thresholds.get("max_bullet_run", 6)
    if best > cap:
        findings.append(("A", f"Bullet run of {best} at one level (cap {cap}). "
                              f"Bullets create hierarchy; a flat run of {best} removes it.", "TRIM"))

    if readability is None:
        findings.append(("A", "PLAIN-ENGLISH CHECK UNAVAILABLE — readability.py could not be "
                              "imported. This is not a pass; run /sharpen manually.", "MUST"))
    elif pw >= 60:
        hits = sorted({t for t in readability.FLAGGED
                       if re.search(r"\b" + re.escape(t) + r"\b", prose_text.lower())})
        if hits:
            findings.append(("A", f"Plain-English breaches: {', '.join(hits[:8])} "
                                  f"(readability.py FLAGGED list).", "MUST"))
    return findings


# ---------------------------------------------------------------- driver

CODE_NAMES = {"B": "story-brief", "G": "genre-mix", "D": "dates", "S": "structure",
              "W": "word-budget", "O": "opening", "A": "ai-texture", "K": "key-info-survival"}


def lint(path, text, genre_override=None, body_text=None):
    """`body_text` (optional) is the SENT version — what actually reached the reader — linted
    against the draft's story brief. Without it the draft's own body is checked."""
    config, cfg_note = load_config()
    readability, read_note = load_readability()
    notes = [n for n in (cfg_note, read_note) if n]

    scoped, why = in_scope(path, config)
    genre = detect_genre(path, text, genre_override)
    result = {
        "path": _norm(path), "genre": genre, "in_scope": scoped, "scope_reason": why,
        "degraded": notes, "findings": [], "verdict": "PASS",
    }
    if not scoped and genre_override is None:
        result["verdict"] = "SKIP"
        return result

    thresholds = (config or {}).get("thresholds", DEFAULT_THRESHOLDS)
    for k, v in DEFAULT_THRESHOLDS.items():
        thresholds.setdefault(k, v)

    lines = classify_lines(text)
    findings = []
    findings += check_story(text, lines)
    findings += check_genre_mix(genre, lines, config)
    findings += check_dates(genre, lines)
    findings += check_structure(genre, lines)
    findings += check_budget(genre, lines, thresholds)
    findings += check_opening(lines, thresholds)
    findings += check_ai_texture(lines, thresholds, readability)
    own_body = " ".join(l for _, l in lines["prose"] + lines["bullet"] + lines["table"] + lines["heading"])
    findings += check_key_info_survival(parse_story(text), body_text if body_text is not None else own_body)

    result["findings"] = [
        {"code": c, "check": CODE_NAMES[c], "severity": sev, "message": m}
        for c, m, sev in findings
    ]
    must = [f for f in result["findings"] if f["severity"] == "MUST"]
    result["must_count"] = len(must)
    result["verdict"] = "REVISE" if must else ("TRIM" if result["findings"] else "PASS")
    return result


def render(r):
    out = []
    head = f"{r['verdict']}  {r['path']}  [{r['genre']}]"
    out.append(head)
    if r["verdict"] == "SKIP":
        out.append(f"  out of scope — {r['scope_reason']}")
        return "\n".join(out)
    for n in r["degraded"]:
        out.append(f"  ! DEGRADED — {n}")
    for f in sorted(r["findings"], key=lambda x: x["severity"] != "MUST"):
        out.append(f"  [{f['severity']} {f['code']}] {f['message']}")
    if r["verdict"] == "PASS":
        out.append("  Bar: acted upon without further interpretation. No findings.")
    elif r["verdict"] == "TRIM":
        out.append("  Craft advisories only — nothing that fails the bar. Ship if the "
                   "reader can act on it.")
    else:
        out.append("  Bar: outputs must be actionable without further "
                   "interpretation. Fix, or add 'guard-exempt: artefact-craft' with a reason.")
    return "\n".join(out)


# ---------------------------------------------------------------- selftest

GOOD_ROADMAP = """---
type: roadmap
story:
  audience: my manager, 1:1, table on screen
  outcome: sign off the Q1 delivery dates
  impact: the squad, the page owner
  key_info: [3 dates, 1 unconfirmed date, 1 ask]
---
# Size guide — Q1

**Ask:** sign off these Q1 dates.

| Deliverable | Date | Owner |
|---|---|---|
| Size profile API live | 2026-10-14 | Squad A |
| Above-the-fold placement test | 2026-11-03 (est.) | Page owner |
| Review-coverage backfill | firm date at the Nov review, TBC | Platform |
"""

BAD_ROADMAP = """---
type: roadmap
---
# Size guide roadmap

The returns landscape continues to evolve and our understanding of the customer
problem has deepened considerably over the last quarter, which means the shape of
the work ahead is somewhat different from what we originally set out in the earlier
planning cycle and it is worth noting that several assumptions have shifted.
Furthermore, the discovery work surfaced a number of insights. Moreover, the team
has raised concerns. Additionally, we should leverage the existing infrastructure.

Our approach to the next quarter reflects the accumulated learning from the earlier
phases of the programme, and the sequencing below has been arranged so that the
dependencies resolve in a sensible order without creating unnecessary contention
between the squads involved in the delivery of the individual workstreams. The
commentary that follows sets out the rationale for each of the choices made, along
with the background context that informed them and the trade-offs considered at
each stage of the planning process across all of the affected teams.

## Risks
- Coverage may be insufficient
- The vendor could churn

## Key findings from discovery
- Customers do not trust the recommendation

## Deliverables
- Ship the size profile
- Backfill reviews
- Rework the placement
"""

BAD_PRD = """---
type: prd
---
# Size Recommendation PRD

| Requirement | Acceptance |
|---|---|
| Show a size | Rendered above the fold |

## Technical approach
The resolver service will call the ladder.

## Data model
A table.
"""


def selftest():
    """Every branch this linter protects must be exercised here, not just the happy path."""
    cases = []

    r = lint("docs/roadmap/good.md", GOOD_ROADMAP)
    cases.append(("good roadmap passes", r["verdict"] == "PASS", r))

    r = lint("docs/roadmap/bad.md", BAD_ROADMAP)
    codes = {f["code"] for f in r["findings"]}
    cases.append(("bad roadmap flags genre-mix", "G" in codes, r))
    cases.append(("bad roadmap flags dates", "D" in codes, r))
    cases.append(("bad roadmap flags structure", "S" in codes, r))
    cases.append(("bad roadmap flags ai-texture", "A" in codes, r))
    msgs = " ".join(f["message"] for f in r["findings"])
    cases.append(("ai-texture catches chain words", "chain" in msgs.lower(), r))
    cases.append(("ai-texture catches 'worth noting'", "worth noting" in msgs.lower(), r))
    cases.append(("plain-english catches 'leverage'", "leverage" in msgs.lower(), r))

    r = lint("docs/plans/x-prd.md", BAD_PRD)
    codes = {f["code"] for f in r["findings"]}
    cases.append(("prd flags solution design", "G" in codes, r))
    cases.append(("prd does NOT run the dates check", "D" not in codes, r))

    r = lint("dashboard/some-roadmap.md", BAD_ROADMAP)
    cases.append(("dashboard path is exempt (skill strength protected)",
                  r["verdict"] == "SKIP", r))
    r = lint("notes/20260101-a-roadmap.md", BAD_ROADMAP)
    cases.append(("notes path is exempt", r["verdict"] == "SKIP", r))
    r = lint("tools/refresh.py", BAD_ROADMAP)
    cases.append(("tools path is exempt (data/AI strength untouched)",
                  r["verdict"] == "SKIP", r))

    # Degradation branch: an unavailable sensor must report UNAVAILABLE, never PASS.
    lines = classify_lines(GOOD_ROADMAP)
    degraded = check_ai_texture(lines, DEFAULT_THRESHOLDS, None)
    cases.append(("absent readability reports UNAVAILABLE, not pass",
                  any("UNAVAILABLE" in f[1] for f in degraded), degraded))

    # A middot-separated list on one line is a list, not one enormous sentence.
    midlist = ("---\ntype: brief\n---\n# X\n\n**Ask:** ship it.\n\n"
               "alpha thing here \u00b7 beta thing here \u00b7 gamma thing here \u00b7 delta thing "
               "here \u00b7 epsilon thing here \u00b7 zeta thing here \u00b7 eta thing here \u00b7 "
               "theta thing here \u00b7 iota thing here \u00b7 kappa thing here\n")
    r = lint("docs/z-brief.md", midlist)
    cases.append(("middot list is not counted as one long sentence",
                  not any("over 30 words" in f["message"] for f in r["findings"]), r))

    # A directory trigger must match a file sitting directly in that directory.
    # fnmatch needs the literal "/", so "dir/**/*.md" alone silently covers nothing.
    r = lint("docs/plans/2026-09-21-usp-technical-approach.md", GOOD_ROADMAP)
    cases.append(("bare file in a triggered directory is in scope",
                  r["verdict"] != "SKIP", r))

    # Opening check: fires on a wall of prose, stays silent when there is a lead-in.
    wall = "---\ntype: brief\n---\n# X\n\n" + "\n".join(
        ["This is a paragraph line that carries no ask and no date at all." ] * 9)
    r = lint("docs/x-brief.md", wall)
    cases.append(("opening fires on an actionless wall of prose",
                  any(f["code"] == "O" for f in r["findings"]), r))
    led = ("---\ntype: brief\n---\n# X\n\n**Ask:** approve the spend.\n\n"
           + "\n".join(["This is a paragraph line that carries no ask or date."] * 9))
    r = lint("docs/y-brief.md", led)
    cases.append(("opening silent when an ask leads",
                  not any(f["code"] == "O" for f in r["findings"]), r))

    # Word budget fires, and only past the budget.
    big = "---\ntype: one-pager\n---\n# X\n\n" + ("word " * 1200)
    r = lint("docs/one-pagers/x-one-pager.md", big)
    cases.append(("word budget fires over budget",
                  any(f["code"] == "W" for f in r["findings"]), r))
    small = "---\ntype: one-pager\n---\n# X\n\n| A | B |\n|---|---|\n| 1 | 2026-10-01 |\n"
    r = lint("docs/one-pagers/y-one-pager.md", small)
    cases.append(("word budget silent under budget",
                  not any(f["code"] == "W" for f in r["findings"]), r))

    # Story brief: absence, gaps, the comment form, the key_info cap, the outcome link.
    def bcodes(r, sev=None):
        return [f for f in r["findings"] if f["code"] == "B"
                and (sev is None or f["severity"] == sev)]
    bare = "---\ntype: brief\n---\n# X\n\n**Ask:** approve the spend.\n"
    r = lint("docs/b1-brief.md", bare)
    cases.append(("missing story brief is MUST", bool(bcodes(r, "MUST")), r))
    gap = ("---\ntype: brief\nstory:\n  audience: my manager\n  outcome: approve the spend\n"
           "  impact: TBC\n---\n# X\n\n**Ask:** approve the spend.\n")
    r = lint("docs/b2-brief.md", gap)
    cases.append(("placeholder + absent fields named as unanswered",
                  any("impact, key_info" in f["message"] for f in bcodes(r, "MUST")), r))
    comment = ("# X\n\n<!-- story\naudience: my manager, email\noutcome: approve the spend\n"
               "impact: squad\nkey_info:\n- 40k budget\n- starts 2026-10-14\n-->\n\n"
               "**Ask:** approve the spend.\n")
    r = lint("docs/b3-brief.md", comment)
    cases.append(("comment-form brief accepted, comment lines not prose",
                  not bcodes(r) and not any(n in (4, 5) for n, _ in
                                            classify_lines(comment)["prose"]), r))
    many = comment.replace("- starts 2026-10-14\n",
                           "".join(f"- fact {i}\n" for i in range(6)))
    r = lint("docs/b4-brief.md", many)
    cases.append(("key_info over cap is TRIM",
                  any("cap 5" in f["message"] for f in bcodes(r, "TRIM")), r))
    buried = comment.replace("**Ask:** approve the spend.", "**Ask:** read the notes.")
    r = lint("docs/b5-brief.md", buried)
    cases.append(("opening that never states the outcome is flagged",
                  any("never states" in f["message"] for f in bcodes(r)), r))

    # key_info survival: the fact in the brief must reach the reader (dates/numbers verbatim).
    def kcodes(r, sev=None):
        return [f for f in r["findings"] if f["code"] == "K" and (sev is None or f["severity"] == sev)]
    kdraft = ("---\ntype: brief\nstory:\n  audience: my manager, email\n  outcome: approve the slip\n"
              "  impact: squad\n  key_info: [sign-off moves to 11 Nov (est.), 25,700 products not 30,000, "
              "one open ask for Friday]\n---\n# X\n\n**Ask:** approve the slip to 11 Nov (est.).\n\n"
              "The test group is 25,700 products, not 30,000. One ask: confirm by Friday.\n")
    cases.append(("bracket key_info keeps the thousands comma in 25,700",
                  parse_story(kdraft)["key_info"][1] == "25,700 products not 30,000", parse_story(kdraft)))
    r = lint("docs/k1-brief.md", kdraft)
    cases.append(("key_info present in own body → no K finding", not kcodes(r), r))
    sent_thin = "Hi, thanks for today. Two things done and my objectives below."
    r = lint("docs/k2-brief.md", kdraft, body_text=sent_thin)
    cases.append(("sent body missing 11 Nov and 25,700 → MUST K",
                  len(kcodes(r, "MUST")) == 2 and "11 Nov" in kcodes(r)[0]["message"], r))
    cases.append(("phrase-only key_info missing → TRIM, not MUST",
                  any("one open ask" in f["message"] for f in kcodes(r, "TRIM")), r))
    r = lint("docs/k3-brief.md", kdraft, body_text=kdraft.split("---\n# X")[1])
    cases.append(("sent body carrying every anchor → no K finding", not kcodes(r), r))
    cases.append(("good roadmap still passes with the K check", lint("docs/roadmap/good.md",
                                                                      GOOD_ROADMAP)["verdict"] == "PASS", None))

    failed = [(n, r) for n, ok, r in cases if not ok]
    for n, ok, _ in cases:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(cases) - len(failed)}/{len(cases)} selftest cases pass")
    if failed:
        for n, r in failed:
            print(f"\n--- {n} ---")
            print(json.dumps(r, indent=1, default=str)[:1400])
    return 0 if not failed else 2


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--path")
    ap.add_argument("--genre")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--triggers", help="exit 0 if the path is in scope, 3 if not")
    ap.add_argument("--body-file", help="the SENT text (email/Teams body) to check the draft's "
                                        "key_info against — what reached the reader, not the draft")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.triggers:
        cfg, note = load_config()
        if cfg is None:
            print(note, file=sys.stderr)
            return 1
        scoped, why = in_scope(a.triggers, cfg)
        print(f"{'IN-SCOPE' if scoped else 'OUT-OF-SCOPE'}  {why}")
        return 0 if scoped else 3

    if a.stdin:
        text = sys.stdin.read()
        path = a.path or "stdin.md"
    elif a.file:
        path = a.file
        try:
            with open(path) as f:
                text = f.read()
        except Exception as e:
            print(f"cannot read {path}: {e}", file=sys.stderr)
            return 1
    else:
        ap.print_help()
        return 1

    body_text = None
    if a.body_file:
        try:
            with open(a.body_file) as f:
                body_text = f.read()
        except Exception as e:
            print(f"cannot read --body-file {a.body_file}: {e}", file=sys.stderr)
            return 1
    r = lint(path, text, a.genre, body_text=body_text)
    print(json.dumps(r, indent=1) if a.json else render(r))
    return 2 if r["verdict"] == "REVISE" else 0


if __name__ == "__main__":
    sys.exit(main())
