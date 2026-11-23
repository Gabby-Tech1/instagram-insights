# Instagram Insights

Pulls Instagram post data, analyses what performs, and recommends what to post next. Every recommendation cites the numbers behind it.

```
Data source ──► SQLite ──► Analytics ──► Intelligence layer ──► Report (Markdown / JSON / API)
(Instagram API              (pandas)      (Claude, or rule-based
 or sample data)                           fallback)
```

## Quick start (no credentials needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py run
```

This runs on `data/sample_posts.json`, 96 posts from a fictional coffee brand, and writes `output/report.md` and `output/report.json`.

### Web dashboard

```bash
uvicorn api:app --port 8000
```

Open http://127.0.0.1:8000. Pick **Sample data** or **My Instagram**, click **Sync posts**, add a line about the account, and click **Analyse & recommend**. The page shows the headline numbers, the recommendations (with copyable caption drafts), key insights, a breakdown by format, topic, day, time, hashtags, caption length and call to action, and the top posts. It's one HTML file (`static/index.html`) served by the API, with no build step.

To get AI recommendations, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Without a key, or if the API call fails, the system uses rule-based recommendations, so it always produces a report.

## Using a real Instagram account

1. The account must be a **Business or Creator** account.
2. Create an app at [developers.facebook.com](https://developers.facebook.com/) and add the **Instagram API with Instagram Login** product.
3. Add the account as an Instagram tester and accept the invite in the Instagram app. While the app is in development mode, you don't need app review for accounts you manage.
4. Generate an access token and put it in `.env` as `IG_ACCESS_TOKEN`. In **Use cases → Customize → API setup**, select a login configuration that includes the insights permission, then click **Generate token** next to the account. Both token types Meta issues are supported:
   - Tokens starting with `IG` (Instagram Login) need nothing else.
   - Tokens starting with `EA` (Facebook or system-user tokens, which never expire) also need `IG_USER_ID` in `.env`. That's the numeric Instagram account ID shown next to the account in the dashboard.
5. Run:

```bash
python main.py run --source instagram --context "What the brand sells and what it's trying to achieve"
```

Meta changes insight metric names from time to time. Each metric is requested separately, so an unsupported one is recorded as 0 instead of breaking the sync. Set `IG_API_VERSION` in `.env` to the current Graph API version.

## Commands

| Command | What it does |
|---|---|
| `python main.py run [--source mock\|instagram]` | Fetch, store, analyse and recommend |
| `python main.py fetch --source instagram --limit 200` | Only pull and store posts. Re-runs refresh metrics, with no duplicates |
| `python main.py analyse --context "..."` | Analyse stored posts and generate the report |
| `python main.py analyse --no-llm` | Rule-based recommendations only |
| `uvicorn api:app --reload` | Dashboard at `/`, plus the JSON API: `POST /api/sync`, `GET /api/stats`, `GET /api/recommendations`, `GET /api/status` (each takes `?source=mock\|instagram`). Docs at `/docs` |
| `pytest` | Run the tests |

## What it analyses

- **Engagement rate** = (likes + comments + saves + shares) / reach, and **reach**. These are tracked separately because they answer different questions: "did people who saw it care?" and "how many people saw it?"
- Breakdowns by **format** (Reel, carousel, image), **topic** (tutorial, behind the scenes, product, promo, community), **day**, **time of day**, **hashtag count**, **caption length** and **call to action**.
- Each segment has a **lift** against the account average (1.33x means 33% better). Segments with fewer than 3 posts are flagged and never used for recommendations.
- Monthly trend, plus the top and bottom 10% of posts.

## Intelligence layer

`insights/intelligence.py` sends Claude **computed stats, not raw posts**: segment tables, top and bottom posts, and the rule-based insights. Claude returns JSON that must match a fixed schema: a summary, key insights, 5 recommendations and a "stop doing" list. Each recommendation includes format, topic, day and time, a caption draft, hashtags, and the **evidence** behind it. Sending stats keeps prompts small and cheap, and stops the model from inventing patterns the data doesn't show.

## Project layout

```
insights/
  models.py        Post model (one shape for every source)
  sources.py       DataSource interface: InstagramSource, MockSource
  store.py         SQLite with upserts
  analytics.py     Segment stats, lift, topic tagging, rule-based insights
  intelligence.py  Claude recommendations + rule-based fallback
  report.py        Markdown report
main.py            CLI
api.py             FastAPI
scripts/generate_mock_data.py   Reproducible sample dataset
tests/
```

## Next steps

- Scheduled daily syncs, and metric snapshots over time to track post growth curves.
- LLM topic tagging to replace the keyword tagger for accounts with varied content.
- Competitor benchmarks through the Business Discovery API.
- A feedback loop: mark which recommendations were posted and score how they performed.
- Multi-account support and a dashboard UI.
