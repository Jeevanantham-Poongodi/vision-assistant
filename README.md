# AI-Powered Vision & Guardian Navigation Assistant

*"See the World Through AI."* Hackathon project.

## Start here
1. Read `docs/00_TEAM_PLAN.md`, then your own story file, then `docs/API_CONTRACTS.md`.
2. The schedule and merge process: `docs/05_IMPLEMENTATION_AND_INTEGRATION_ROADMAP.md`.

## Branches (never push to `main`)
| Branch | Owner |
|---|---|
| `main` | Protected. Only PRs from `integration`, merge commit only |
| `integration` | Checkpoint merges (Integration Captain: Coder 3) |
| `frontend-ui` | Coder 1 |
| `ai-core` | Coder 2 |
| `backend-api` | Coder 3 |
| `voice-ocr` | Coder 4 |
| `qa-docs` | Member 5 |

Commit messages start with the story ID: `[CV-03] add pinhole distance estimation`.
After every checkpoint: `git merge origin/main` into your own branch.

## Run locally
```bash
# backend (Python 3.11)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000                # http://localhost:8000/docs

# frontend (Node 20) — Coder 1 scaffolds it in Phase 0
cd frontend && npm ci && npm run dev -- --host
```

## Sections per owner
<!-- Each owner adds setup notes under their own heading only. -->
### Coder 1 — Frontend
### Coder 2 — AI Vision
### Coder 3 — Backend
### Coder 4 — Integrations
### Member 5 — QA
