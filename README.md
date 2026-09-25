# Jan Samadhan — deployable software (SIH 2026, PS 26043)

A citizen-problem-to-implemented-solution platform: citizens report problems, AI
triages them, experts verify, AI matches the best-fit college, students + faculty
build a solution, industry funds/mentors it, government approves and implements it,
and the citizen rates the result — all tracked on a live dashboard.

## Zero setup required

This backend is written in **pure Python standard library** — no `pip install`,
no virtual environment, no Node build step. If the machine has Python 3.9+, it runs.

```
python3 server.py
```

Then open **http://localhost:8000** in a browser. That's it — the same server
serves both the API and the frontend.

Change the port or secret if you like:
```
PORT=8080 JAN_SAMADHAN_SECRET="something-long-and-random" python3 server.py
```

## What's in this zip

```
server.py          — the entire backend: HTTP server, SQLite database, AI triage,
                      college matching, auth, and all 9 workflow endpoints
frontend/
  index.html        — app shell + login/register screen
  app.js            — all frontend logic, wired to the real API (no hardcoded data)
  styles.css        — styling
test_e2e.py         — automated end-to-end test that exercises the full 9-step
                      pipeline against a running server
README.md           — this file
```

No `requirements.txt` because there is nothing to install for the backend.
`test_e2e.py` uses the `requests` library only for testing — install it with
`pip install requests` only if you want to run the test yourself; the app itself
never needs it.

## This has been tested — how to verify it yourself

Run the automated end-to-end test against a live copy of the server:

```
python3 server.py &                  # start the server in the background
python3 test_e2e.py                  # runs the full 9-step pipeline over real HTTP calls
```

The test script registers one account per role (citizen, expert, college, industry,
government), submits a real problem, and drives it through every stage — triage,
verification, AI matching, college acceptance, a submitted solution, industry
funding, government approval, implementation, and citizen feedback — then checks
the dashboard numbers and the full audit trail. It also checks negative cases:
wrong password, duplicate email, wrong role attempting an action, duplicate
feedback, and that one citizen can't see another citizen's problem.

**This was run before handing the zip over. All checks passed:**
```
30 checks — 30 PASS, 0 FAIL
```

## Try it by hand (demo flow)

1. Open the app, click **Register**, create a **citizen** account.
2. Register a **college** account too — set its "Expertise keywords" to something
   like `water, civil, iot` so AI matching has something to match against.
3. Register an **expert**, an **industry**, and a **government** account.
4. As the citizen: **Report Problem** → describe something (e.g. "Water shortage in
   village, tanker urgent") → see the AI-assigned category and priority.
5. As the expert: **Verify Problems** → open it → **Verify & approve** → AI matches
   it to the college you registered.
6. As the college: **Matched Problems** → open it → **Accept** → then **Submit
   solution**.
7. As the industry: **Support Problems** → open it → submit funding/tech/mentorship.
8. As the government: **Approve & Implement** → approve, then mark implemented.
9. Back as the citizen: open the problem → leave a rating.
10. Any role → **Dashboard** → see the live totals update.

## Architecture

- **Backend**: `http.server` (stdlib) with hand-rolled routing, SQLite for storage,
  HMAC-signed bearer tokens for auth (no external JWT library needed), PBKDF2 for
  password hashing.
- **AI triage**: keyword-based category/priority classifier, works fully offline.
  If you want to swap in a real LLM call (e.g. the Claude API) later, replace the
  body of `ai_triage()` in `server.py` — the rest of the pipeline doesn't change.
- **AI matching**: scores keyword overlap between a problem and each college's
  declared expertise, returns the top 3.
- **Frontend**: plain HTML/CSS/JS, no build step, no framework — talks to the
  backend only through `fetch()` calls to `/api/...`.

## Before a real production deployment

- Set `JAN_SAMADHAN_SECRET` to a long random value (don't use the default).
- Put this behind HTTPS (e.g. a reverse proxy like Caddy or nginx).
- Move from SQLite to PostgreSQL if you expect concurrent write load at scale.
- Add rate limiting on `/api/register` and `/api/login`.
- Currently anyone can register as any role — add an admin-approval step for
  expert/college/industry/government sign-ups before going live.
