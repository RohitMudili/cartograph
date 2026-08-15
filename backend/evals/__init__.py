"""Cartograph eval harness — golden Q&A with citation precision/recall.

Grades the full retrieve → route → synthesize → verify chain against a golden
dataset of questions with known-good citation targets and answer facts. The
scoring is deliberately deterministic (path/keyword matching, no LLM judge) so
a run's only model spend is the answers being graded, and two runs on the same
answers always score the same.

Run it (needs backend/.env with DB + LLM keys, and the repo already indexed):

    cd backend
    uv run python -m evals                       # pybktree golden set
    uv run python -m evals --repo <url> --golden evals/golden/<set>.json
    uv run python -m evals --index               # index the repo first if needed

Output: a per-question table + aggregate scoreboard, printed and written to
`evals/results/`.
"""
