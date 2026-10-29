# Source coverage and integration notes

Endpoint checks below were performed on 2026-10-29. They confirm that the public endpoint responded and returned parseable records during that check; they do not guarantee future availability or verify the source's terms of use.

## Global remote jobs

| Source | Integration | Endpoint check |
|---|---|---|
| We Work Remotely | Public RSS | Parsed 25 listings |
| Remote OK | Public JSON API | Parsed 99 listings |
| Himalayas | Public jobs API | Parsed 20 listings |
| Remotive | Public JSON API | Parsed 12 listings |
| Jobicy | Public jobs API | Parsed 100 listings |
| Arbeitnow | Public job-board API | Parsed 300 listings |
| Working Nomads | Not integrated | The probed RSS URL returned HTTP 404; no replacement feed/API was verified |
| Remote.co | Not integrated | The public feed probe timed out; no stable public API/feed was verified |

Jobs are persisted for AI/ML roles even when experience, remote status, or India eligibility is unknown. A primary alert is sent only for fresher/graduate/junior roles with a fully remote signal and explicit India eligibility. Unknown values remain unknown. The global sources are not a source of India onsite/hybrid postings.

## India job sources

Cutshort, Naukri, Wellfound, and National Career Service are not integrated. During the endpoint check, Naukri returned HTTP 403; the other portals loaded their public pages, but no documented public job API/feed was verified. Company career pages are not crawled: no company allowlist or aggregate public feed is configured. No login, CAPTCHA, or access-control workaround is used.

These checks are endpoint smoke tests, not a review or approval of each portal's terms. `india_jobs.py` reports counts for India Remote, India Hybrid, and India Onsite records already collected by configured sources. An empty category is not evidence that no such jobs exist. Use of these portals for automated collection requires an official API/feed and review of its access terms.

## AI news

The existing news engine covers OpenAI, Google DeepMind, Anthropic, Hugging Face, NVIDIA, Microsoft Research, Google Research, AWS Machine Learning, MIT Technology Review AI, and arXiv AI/ML/vision/statistical-ML feeds.

All 13 configured endpoints were fetched and parsed during the endpoint check, producing 162 new items across six assigned topic categories. News has separate URL/content deduplication and is sent in separate Telegram digests. A digest is not sent when no new relevant items are pending, and a total source failure stops the news run rather than being represented as a successful zero-item day.

## Daily skill report

Job observations and source-run outcomes are recorded in `career_intelligence.db`. Skill metrics use distinct normalized company/role listings, separated into fresher, junior (up to two years), all AI/ML, India-eligible remote, India hybrid/onsite, and India-restricted groups. Trend comparisons are suppressed unless periods have complete coverage from the same configured sources and enough distinct listings.

The daily report is scheduled for 00:00 Asia/Kolkata (`30 18 * * *` UTC). It requires `BOT_TOKEN` and `CHAT_ID` as GitHub Actions secrets. For local runs, place them in `.env`, which is excluded by `.gitignore`.
