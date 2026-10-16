# ai-native-pm

Tools from one product manager's AI-run workflow, published one a week.

Each is something that runs in my own system every day, extracted, de-identified and given a self-test so you can drop it into yours. No prompts-as-content, no essays. Scripts, configs and the hook wiring that makes them fire automatically.

## Who this is for

Product managers who already use AI for drafting and analysis and have hit the second-order problems: documents that read well and cannot be acted on, automation that reports success when nothing happened, a decision queue that grows faster than one person can clear it.

## Tools

| Week | Tool | What it does |
|---|---|---|
| 01 | [artefact-lint](weeks/01-artefact-lint/) | Fails a PRD, roadmap, brief or status update when the reader could not act on it without asking a question. Dates, genre mix, story brief, AI texture, and whether the sent version kept the key facts. |
| 02 | heartbeats | Receipts and a fail-closed timeout wrapper so scheduled AI jobs cannot report "ok" over a dead run |
| 03 | idempotency ledger | Re-run any AI skill on the same input without double-writing to shared files |
| 04 | episodic recall | Local semantic search over your own past AI sessions, so you find what was already tried before you plan |

Weeks 02 onward are the plan. A week is real when it has a tag and a changelog line.

## How each week is built

1. The tool runs in my private system for weeks first.
2. It is extracted into this repo with private paths, names and numbers removed, and a `--selftest` that exercises every branch including the ones that run when something is missing.
3. A publish gate scans for anything that should not leave my machine.

## What is not here

Anything built for my employer stays with my employer. This repo is the operating layer, never the work product.

## Licence

MIT.
