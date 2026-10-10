# Compliance Sentinel Agent — Build Plan

Portfolio P1 · W05 session deliverable · Agentic System

A LangGraph agent that scrapes regulatory sites daily, audits a codebase against new rules, and generates an audit-ready PDF report with citations. Deliverables: public GitHub repo and a Loom demo.

**Stack:** LangGraph · Playwright · pgvector + RAG · BullMQ + Fly.io · WeasyPrint

## 1. Decisions to lock first

1. **Regulatory domain: data privacy (GDPR plus CCPA).** Privacy rules map to things detectable in code: PII in logs, missing encryption, retention and consent handling. Scrape two or three sources only: EDPB guidelines, EUR-Lex and the California CPPA regulations page.
2. **Target codebase: a small demo repo with seeded violations.** A small Flask or Express app with 10–15 planted issues. This gives ground truth for measuring the agent and a predictable demo. Any other repo can be audited through a `--repo` URL.
3. **Language split: Python for everything except the scheduler.** LangGraph, Playwright and WeasyPrint are all Python, while BullMQ is Node-first. Use a tiny Node process that owns the daily repeatable job, with a Python BullMQ worker consuming it. Check whether the Python `bullmq` package supports repeatable jobs; if it does, drop the Node piece.
4. **Develop in Docker from day 1.** WeasyPrint needs Pango/GTK native libraries, which are painful on Windows. The same image deploys to Fly.io.

## 2. Architecture

```
Node scheduler (BullMQ repeatable, daily)
        │  Redis (Upstash)
        ▼
Python worker ──► 1. Scrape   Playwright → raw HTML/PDF, content hash for change detection
                  2. Ingest   parse → chunk by article/section → embed → pgvector
                  3. Audit    LangGraph agent over target repo
                  4. Report   Jinja2 HTML → WeasyPrint PDF
                  5. Alert    Slack webhook / email if critical findings
Postgres + pgvector (Fly Postgres or Neon): regulations, chunks, runs, findings
```

### LangGraph audit graph

1. `load_new_rules` — picks up the rules changed since the last run.
2. `extract_obligations` — the LLM turns legal text into a structured, testable checklist.
3. `scan_codebase` — runs once per obligation, using grep and AST tools plus file reads.
4. `evaluate_finding` — retrieves the cited regulation text and grades severity and confidence.
5. `verify` — a second pass that drops findings without both a code location and a rule citation.
6. `compile_report` — assembles the output.

Use the Postgres checkpointer so runs are resumable.

### Data model

| Table | Purpose |
|---|---|
| `sources` | Regulatory portals, adapter name, last scraped time |
| `documents` | Raw snapshot, content hash, URL, retrieval date |
| `chunks` | Section text, article/section metadata, embedding |
| `obligations` | Structured checklist items derived from chunks |
| `runs` | One row per pipeline run, status, token cost |
| `findings` | File, line, snippet, obligation, cited chunk, severity, confidence, remediation |

### Proposed repo layout

```
compliance-sentinel/
├── scheduler/            Node: BullMQ repeatable job
├── sentinel/
│   ├── scrapers/         one adapter per source, common interface
│   ├── ingest/           parsing, chunking, embedding
│   ├── rag/              hybrid retrieval
│   ├── agent/            LangGraph graph, nodes, tools
│   ├── report/           Jinja2 templates, WeasyPrint rendering
│   ├── alerts/           Slack, email
│   └── worker.py         BullMQ worker entry point
├── demo_repo/            seeded-violation target app
├── evals/                ground truth and scoring script
├── migrations/
├── docker-compose.yml
├── Dockerfile
└── fly.toml
```

## 3. Build schedule

| Day | Goal | Done when |
|---|---|---|
| 1 | Repo scaffold, Docker Compose (Postgres with pgvector, Redis), schema, seeded demo repo | `docker compose up` runs and migrations apply |
| 2 | Playwright scrapers with hash-based change detection; chunking and embedding ingest | A second run on unchanged sources ingests nothing new |
| 3 | Legal RAG retrieval (hybrid vector plus keyword, with section metadata); obligation extraction | A query returns the correct article with its citation |
| 4 | LangGraph audit agent with code-search tools and a verification node | It finds at least 70% of the seeded violations with few false positives |
| 5 | PDF report and Slack/email alerts | One command produces the PDF from a fresh scrape |
| 6 | BullMQ cron, Fly.io deploy, secrets, a manual-trigger endpoint | A scheduled run completes on Fly without intervention |
| 7 | Evaluation numbers, README, Loom recording | The public repo is ready to share |

## 4. Report contents

- **Executive summary:** counts by severity and what changed since the last run.
- **Findings table:** file and line, code snippet, regulation article quoted verbatim, source URL with retrieval date, and remediation.
- **Appendix:** the rules checked and the run metadata.

Every finding must carry both a code location and a citation; that is what makes the report audit-ready.

## 5. Evaluation

- Ground truth: the seeded violations in `demo_repo/`, listed in `evals/ground_truth.json`.
- Metrics: recall on seeded violations, false positives per run, citation accuracy (quoted text exists in the cited chunk), cost and duration per run.
- Target: at least 70% recall with 100% citation accuracy.

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated citations | Quote only from retrieved chunks; the verification node checks that the quoted text exists in the store |
| Scraper fragility | One adapter per source behind a common interface, raw snapshots saved, alert on zero-result scrapes |
| Cost on large repos | Pre-filter files with grep and embeddings before the LLM reads them; cap tokens per run |
| Demo depends on new rules appearing | A `--simulate-amendment` flag injects a rule change so the full path can be shown |
| "Saves 40+ hours/week" is unmeasured | Present it as a target in the README, or back it with a timed manual audit versus the agent |

## 7. Loom outline (3–4 minutes)

1. State the problem in 20 seconds.
2. Trigger a run with a simulated amendment.
3. Show the LangGraph trace in LangSmith.
4. Open the PDF and click through one citation.
5. Show the Slack alert.
6. Close on the architecture diagram and the evaluation numbers.

## 8. Definition of done

- [ ] Daily scheduled run completes on Fly.io without intervention
- [ ] Scrapers detect changes and skip unchanged sources
- [ ] Agent audits the demo repo and meets the evaluation targets
- [ ] PDF report generated with a verified citation on every finding
- [ ] Slack/email alert fires on critical findings
- [ ] Public GitHub repo with README, architecture diagram and evaluation results
- [ ] Loom demo recorded and linked in the README
