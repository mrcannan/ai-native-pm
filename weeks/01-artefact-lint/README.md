# artefact-lint

You paste an AI-drafted roadmap, PRD, brief or status update into this and it tells you, line by line, why your manager will have to ask a question before they can act on it. No dates on three items. A risks section that does not belong. Four phrases that read as AI. Fix those, run it again, send.

Think of it as a spell-checker for structure. Spell-check says "this word is wrong". This says "line 8 has no date".

## Try it in 30 seconds

```bash
git clone https://github.com/mrcannan/ai-native-pm && cd ai-native-pm/weeks/01-artefact-lint
python3 artefact_lint.py examples/q1-roadmap.md
```

You will see:

```
REVISE  examples/q1-roadmap.md  [roadmap]
  [MUST B] No story brief. Answer these four in frontmatter `story:` before drafting: audience, outcome, impact, key_info.
  [MUST G] Roadmap is mixing genres. Risks, decision logs and findings are not roadmap; move them to a linked file. Sections: L10 ## Risks; L13 ## Decisions
  [MUST D] 3/3 in-flight items carry no date (L8; L11; L14). Every in-flight item needs a date — committed, '(est.)', or when the firm date gets confirmed.
  [MUST A] AI tells present: comprehensive overview, ever-evolving, in today's, it's worth noting. Strip them.
  [MUST A] Enumeration chain (furthermore, moreover) reads as generated. Use 'Also', or make it a list.
```

Now run it on the fixed version, `examples/q1-roadmap-fixed.md`, and it passes. Open both files side by side; the difference is the whole point.

Three files, no dependencies beyond Python 3.9+.

```
artefact_lint.py      the checker (run --selftest first)
readability.py        plain-English word list and scorer, imported by the checker
artefact-craft.json   which files to check, word budgets, genre rules. Edit to taste.
examples/             a bad roadmap and its fixed twin
```

## Why

AI makes a document fast to produce and slow to use. The usual failure is not that the draft is wrong, it is that it blends genres (a roadmap carrying risks, a PRD carrying solution design), skips dates, opens with context instead of the ask, and keeps the texture of generated prose. The reader then re-runs AI to decode it. This tool catches those defects before the document leaves your machine.

It deliberately does not lint analysis, dashboards, SQL, notebooks or code. The problem it targets is editing discipline in documents.

## All the ways to run it

```bash
python3 artefact_lint.py --selftest                 # 31 cases, every check exercised
python3 artefact_lint.py docs/q1-roadmap.md         # lint one file
python3 artefact_lint.py draft.md --body-file sent.txt   # did the sent version keep the key facts?
python3 artefact_lint.py --triggers docs/x.md       # exit 0 if the path is in scope
cat draft.md | python3 artefact_lint.py --stdin --path docs/brief.md --json
```

Exit codes: `0` pass or out of scope, `2` findings, `1` usage error.

## What it checks

| Code | Check | Severity |
|---|---|---|
| B | Story brief present and complete in frontmatter: `audience`, `outcome`, `impact`, `key_info` (max 5) | MUST |
| G | Genre mix: roadmap sections named risk/decision/finding/background; PRD sections named architecture/data model/technical approach | MUST |
| D | Dates: every bullet or table row under an in-flight heading carries a date, `(est.)`, or `TBC` with when | MUST |
| S | Structure: in a plan artefact, prose lines must not outnumber table rows and dated items | MUST |
| O | Opening: the document states the ask or shows the dated table within the first few lines | MUST |
| A | AI texture: flagged terms, em-dash density, sentences over 30 words, bullet runs over 6 | MUST / TRIM |
| W | Word budget per genre (roadmap 1,500; one-pager 900; status 900; brief 2,200; PRD 3,000) | TRIM, MUST past 2× |
| K | With `--body-file`: every `key_info` item survived into the text you actually sent | MUST |

MUST findings set the verdict to REVISE. TRIM findings alone give TRIM, which means ship if the reader can act on it.

If a check cannot run (config missing, readability.py unimportable) the report says `DEGRADED` and that check reports UNAVAILABLE. It never reports a pass it did not earn.

## The story brief

The B check expects four answers in the document's frontmatter, written before drafting:

```yaml
---
type: roadmap
story:
  audience: my manager, 1:1, table on screen
  outcome: sign off the Q1 delivery dates
  impact: the squad, the page owner
  key_info: [3 committed dates, 1 unconfirmed date and when it firms, 1 ask]
---
```

In a document that ships as-is, use an HTML comment (`<!-- story ... -->`) with the same four lines. If you cannot answer one of the four, the artefact is not ready to draft.

## Scope

`artefact-craft.json` decides which paths are linted. Default triggers are any file whose name contains `prd`, `roadmap`, `one-pager`, `brief`, `status` or `update`, plus anything under `docs/plans`, `docs/roadmap`, `docs/one-pagers`. Default exemptions include `tools/`, `dashboard/`, `notes/`, `archive/`, templates and READMEs. Globs are matched relative to the directory you run from. Point `ARTEFACT_LINT_CONFIG` at your own file to override.

Per-file bypass: put `guard-exempt: artefact-craft — <reason>` in the first 20 lines.

## Run it on every save (Claude Code)

Add a PostToolUse hook so the linter runs each time Claude writes or edits a file. Warn-only; it never blocks the write.

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write|Edit",
      "hooks": [{
        "type": "command",
        "command": "f=$(jq -r '.tool_input.file_path'); python3 /path/to/artefact_lint.py --triggers \"$f\" >/dev/null 2>&1 && python3 /path/to/artefact_lint.py \"$f\" || true"
      }]
    }]
  }
}
```

The `--triggers` call keeps it quiet on files that are out of scope.

## Adapting it

- Word budgets, thresholds and genre patterns live in the JSON. Change those before changing code.
- `readability.py` holds the flagged-term list. Add your organisation's own management-speak there; the linter imports it so there is one list.
- Add a genre by extending `detect_genre` and the `word_budget` map.
