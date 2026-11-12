# Source coverage and integration notes

Endpoint checks below were performed on 2026-11-12. Counts are records returned during that check, not counts of AI/ML jobs. They confirm that the public endpoint responded and returned parseable records; they do not guarantee future availability or independently verify every listing.

## Global remote jobs

| Source | Integration | Endpoint check |
|---|---|---|
| We Work Remotely | Public RSS | Parsed 25 listings |
| Remote OK | Public JSON API | Parsed 98 listings |
| Himalayas | Public jobs API | Parsed 20 listings |
| Remotive | Public JSON API | Parsed 14 listings |
| Jobicy | Public jobs API | Parsed 100 listings |
| Arbeitnow | Public job-board API | Parsed 300 listings |
| Anthropic | Public Greenhouse job-board API | 670 listings returned |
| Databricks | Public Greenhouse job-board API | 909 listings returned |
| Scale AI | Public Greenhouse job-board API | 170 listings returned |
| **Total** | **9 distinct employer/job-board sites** | **2,306 records returned** |
| Working Nomads | Not integrated | The probed RSS URL returned HTTP 404; no replacement feed/API was verified |
| Remote.co | Not integrated | The public feed probe timed out; no stable public API/feed was verified |
| Jobspresso | Not integrated | Its public RSS feed returned no entries during the latest check |

The three company sources use Greenhouse's public job-board endpoints and link to the employers' listed postings. Their full listings are passed through the same AI/ML and remote-status filters as other sources; country or location restrictions are retained rather than treated as worldwide eligibility. Listings are not independently validated, and application links remain labeled unverified.

AI/ML listings are retained when experience, remote status, or India eligibility is unknown. Alerts cover fully remote roles without a known over-two-years requirement or explicit senior title; unknown experience and India eligibility are labeled as unknown. India eligibility is evaluated separately from worldwide remote claims. Hybrid and onsite listings are classified and stored but are not sent as remote-job alerts.

## India job sources

Cutshort, Naukri, Wellfound, and National Career Service are not integrated. During the endpoint check, Naukri returned HTTP 403; the other portals loaded their public pages, but no documented public job API/feed was verified. No company career pages are scraped; only the three configured public Greenhouse job-board APIs are queried. No login, CAPTCHA, or access-control workaround is used.

These checks are endpoint smoke tests, not a review or approval of each portal's terms. `india_jobs.py` reports counts for India Remote, India Hybrid, and India Onsite records already collected by configured sources. An empty category is not evidence that no such jobs exist. Use of these portals for automated collection requires an official API/feed and review of its access terms.

## AI/ML news and reports

The news engine covers official feeds/pages for OpenAI, Google DeepMind, Anthropic, Hugging Face, NVIDIA, Microsoft Research, Google Research, AWS Machine Learning, and arXiv AI/ML/vision/statistical-ML feeds. MIT Technology Review was removed so the configured list matches the requested first-party and research sources.

Items must match AI/ML topics before storage. URLs and similar article content are deduplicated. Important new items can trigger a Telegram update; the daily report ranks up to ten recent items and includes the publisher, source date when available, publisher-provided summary, topic, and article URL. Research-feed items are labeled as papers. A daily report is recorded once per Asia/Kolkata calendar date; empty reporting windows are stated as empty rather than filled with invented stories.

## Architecture and scheduling

`main.py` is the orchestration entry point. It runs the job engine and then the news engine independently, so a failed engine does not prevent the other from running. The GitHub Actions workflow runs hourly and at 00:00 Asia/Kolkata (18:30 UTC) for the daily news report. Manual workflow dispatch also requests the daily report, with database deduplication preventing another post on the same local date.

The workflow uses the existing `BOT_TOKEN` and `CHAT_ID` secrets. For local runs, set them in `.env`, which is excluded by `.gitignore`, then run `python main.py`; use `python main.py --daily-report` to request the once-per-day report.
