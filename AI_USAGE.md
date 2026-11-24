# AI-assisted development: how I worked

I used **Claude Code** as an implementation accelerator on this project. My working model is the one I'd use with a fast engineer on the team:

- **I own** the problem framing, scope, plan approval, acceptance criteria, real-world testing and what gets merged.
- **The agent drafts:** it proposes designs, writes the implementation and tests, and runs the checks I require before anything is accepted.

The value of the tool was speed. The quality came from the constraints around it.

## Workflow

```
frame the goal → agent proposes a plan → I review/approve → small increments → verify (tests, live data, browser) → I approve the commit
```

1. **Frame:** state the outcome and constraints, not the steps. For example: "simple system, functionality over UI, get something working first", and later "match the test spec".
2. **Plan before code:** for the test-spec rework, the agent first produced a gap analysis against every spec requirement, with priorities. I approved the scope ("build everything, I'll supply the API key") before any code changed.
3. **Small increments:** one component at a time (sources → analytics → intelligence → API → UI), with the test suite run after each.
4. **Verify against reality, not just tests:** a live Instagram account, a live Claude run, and the dashboard checked in a real browser (desktop, mobile, light and dark).
5. **Gated merges:** nothing is committed or pushed without my explicit approval. During the spec rework I froze commits entirely until I had reviewed the full change set.

## Guardrails

| Guardrail | Why | How it's enforced |
|---|---|---|
| No commit or push without approval | I'm accountable for what ships | Explicit instruction for the session; commits made under my account only after review |
| Secrets never in chat or in the repo | Agent sessions and repos aren't secret stores | Tokens live only in `.env` (git-ignored); credentials checked by prefix only, never printed; diffs scanned for key patterns before commits; tokens removed from API error messages |
| AI failure must not break the product | An LLM is an unreliable dependency | Every LLM call has a deterministic rule-based fallback, and the UI always shows which engine produced the output |
| Recommendations must be backed by data | The spec's core requirement, and the main risk of LLM output | The model receives computed stats, not raw posts; output must match a JSON schema; every cited number is checked against the data (`grounding.py`) |
| Official APIs only | It must be something a client could actually run | Instagram Graph API; no scraping |
| Tests never touch real credentials or the network | Deterministic, safe CI | `conftest.py` removes credentials; Instagram and Claude are faked |

## What I delegated vs owned

| Delegated to the agent | Owned by me |
|---|---|
| Implementation of the sources, storage, analytics, intelligence layer, API and dashboard | Scope and priorities: core workflow first, UI later, then the spec gaps |
| Test suites (unit, API, fake Instagram and Claude) | Approving the architecture and the spec gap plan before work started |
| Diagnosing API responses and failures | The Meta app setup: business portfolio, tester role, login configuration, access token |
| Drafting the README, TECHNICAL.md and this document | Running the system against my real Instagram account and the live Claude API |
| Sample-data generator with known patterns built in | Acceptance: reviewing results and approving every commit; keeping the repo private until submission |

## Issues caught during development

The useful signal here is *how* problems were caught. Many came from verifying against real data rather than from reading generated code. Several were mistakes in AI-generated code or reasoning, caught by the verification steps above.

| # | Issue | Caught by | Resolution |
|---|---|---|---|
| 1 | The topic tagger matched hashtags and filler words ("#brew**guide**", "we've **learn**ed"): 47 of 96 posts tagged "tutorial" | Group counts didn't match the planted sample data | Tag only the caption text, with tighter rules. Later replaced by AI tagging with the keyword rules as fallback |
| 2 | Timing insights based on engagement rate alone ("post in the morning") were misleading | Reviewing the first insights | Every group now reports reach alongside engagement rate |
| 3 | **A 1500% engagement rate** on my real account: Meta reported reach = 1 for a post with 15 interactions | Live run on my account | Posts with reach under 10 are excluded from rates. Covered by a test |
| 4 | Posts with zero reach were silently dropped | Same live run: 1 of 2 posts analysed | Keep every post; only the rate is left blank |
| 5 | Confident "patterns" from 2 posts | Same live run | Below 10 measurable posts, the system gives a testing plan instead of patterns |
| 6 | The access token was rejected: Meta issued a Facebook-style system-user token, but the code targeted Instagram Login | Probing both API hosts with the token | The source detects the token type and routes to the right host |
| 7 | Mixed timezone formats between the API and sample data | Warning during the live run | Normalise to UTC; optional `ACCOUNT_TIMEZONE` |
| 8 | `NaN` in the JSON output for accounts without reach data | Reviewing `report.json` | Serialise as `null` |
| 9 | The dashboard broke when opened as a file instead of through the server | Browser check | The page detects this and explains how to open it |
| 10 | Claude returned 401 (invalid key). The fallback worked, but the agent wrongly concluded from the key's prefix that it wasn't an API key | Live run; my replacement key, with the same prefix, worked | New key, and a rule: validate credentials with a free API call, never by their format |
| 11 | The browser preview tool couldn't start the server (macOS privacy restriction on Downloads) | Tooling error | Ran the server from the terminal |
| 12 | A generated test assumed the wrong API call order | Test failure | Fixed the test, not the code |
| 13 | Recommendation labels were inconsistent ("community" ideas with the "how-to" style) | Reviewing the dashboard in the browser | Each idea takes the style of the proven post it builds on |
| 14 | `.env.example` had been truncated (only `IG_USER_ID` left) | Doc review | Rewritten with a "copy, don't move" note |
| 15 | **A 200% save rate:** new metrics repeated bug #3 | Checking the redesigned UI on my real account at phone width | Same rule applied to save and share rates. Covered by a test |
| 16 | **The number check was too lenient:** an invented "9.99x" could pass if any number in the stats happened to be 9.99 | An adversarial test fed it invented numbers | Multipliers must match real lifts, and percentages real rates or changes. Re-verified against both live AI runs |

Bugs #3, #5, #6 and #15 only exist with real data. Connecting a real account early mattered more than any amount of generated code. Bugs #1, #10, #12, #13, #15 and #16 were AI mistakes, caught because "it ran" was never the acceptance bar.

## Verification

- **30 automated tests:**
  - the Instagram source: pagination, both token types, the per-metric fallback, retries, no token leakage
  - analytics, checked against planted patterns
  - the intelligence layer with a fake Claude: refusal, invalid JSON, invented numbers
  - the grounding check
  - the API end to end
- **Live Instagram:** my Creator account through the Graph API, re-run after every change to data collection.
- **Live Claude (Opus 5.5) on the 96-post sample:**
  - The AI tagging produced meaningful topics: "brewing guides", "customer setups", "sales & discounts".
  - All 5 recommendations passed the number check, as did every number in the summary and improvements (34–41 per run).
  - A second run reused the cached tags, confirming the cache.
- **Output quality review:** the first live AI run cited internal field names and raw fractions ("reach_lift 1.12", "0.1182"). The prompt was tightened to require readable figures and caption references, and the run repeated to confirm.
- **Browser checks** of the dashboard after each UI change: both data sources, every section, desktop, mobile, light and dark.

## Takeaways

- **Constraints beat instructions.** "Plan first, no commits, every number must be traceable" produced better output than step-by-step prompting.
- **Test against reality early.** The highest-impact bugs came from the live account and the live model, not from code review.
- **Treat LLM output like any untrusted input:** schema-validated, checked against the data, with a deterministic fallback.
- **Bugs that could come back became tests** (#1, #3, #5, #6, #15, #16).

The full agent session transcript is available on request.
