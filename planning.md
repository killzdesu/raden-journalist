# Research Digest Bot — Implementation Plan

## 1. Tech Stack Decision

| Layer | Choice | Reason |
|---|---|---|
| Language | **Python 3.11** | Best ecosystem for research APIs and LLM integration |
| Scheduler | **Linux Cron** | Lightest possible on 512MB VPS, no daemon needed |
| HTTP Client | **httpx** | Async-capable, modern, handles timeouts well |
| Database | **SQLite** | Zero extra RAM, no server process, perfect for this scale |
| LLM API | Gemini API | Free tier sufficient for ~20 articles/day |
| Discord | **Webhook** (not Bot token) | Simpler, no library needed, just HTTP POST |
| Config | **.env + python-dotenv** | Secure credential management |

## 2. Data Sources

### Primary Source — PubMed E-utilities
- **Why:** Most comprehensive, free, covers all target journals, returns structured metadata + abstracts
- **What we get:** PMID, Title, Abstract, Authors, Journal, DOI, Publication Date
- **Flow:** Call `esearch` to get IDs → Call `efetch` to get full details
- **Rate limit:** 3 req/sec without key, 10 req/sec with free NCBI API key
- **API key:** Register free at NCBI for higher limits

### Secondary Source — Europe PMC
- **Why:** Backup if PubMed misses anything, good for open-access articles
- **Use case:** Run as fallback only, not primary

## 3. Target Journals List

Articles will be fetched from these journals using their Online ISSNs in the PubMed API query:
- JACI (1097-6825)
- JACI: In Practice (2213-2201)
- Allergy (1398-9995)
- Clinical & Experimental Allergy (1365-2222)
- Annals of Allergy, Asthma & Immunology (1942-3933)
- Pediatric Allergy and Immunology (1399-3038)
- Clinical and Translational Allergy (2045-7022)
- World Allergy Organization Journal (1939-4551)
- Frontiers in Allergy (2673-6101)
- Allergy, Asthma & Immunology Research (2092-7363)

## 4. Article Filtering Rules

Articles will be **excluded** if they are:
- Publication types: Letter, Comment, Erratum (Applied directly in PubMed API query)
- Language: Non-English (Applied directly in PubMed API query)
- Already sent before (checked against database)
- No abstract available (title-only records)

Articles will be **included** if they are:
- Original Research, Review, Systematic Review, Meta-Analysis, Clinical Trial
- Published within the last 3 days (adjustable, applied directly in PubMed API query)

## 5. Application Modules

### Module 1 — Fetcher
- Query PubMed with journal list + date filter
- Retrieve article metadata and abstracts
- Return structured list of article objects

### Module 2 — Deduplicator
- Check each fetched article against SQLite database
- Skip any article whose PMID already exists in DB
- Save new PMIDs to DB immediately after fetching

### Module 3 — Summarizer
- Send title + abstract to LLM API
- Use a fixed prompt template designed for clinical audience
- Receive structured summary back
- Summary sections: Key Finding, Study Design, Main Results, Clinical Relevance, Limitations

### Module 4 — Discord Notifier
- Send one **header message** per run (date + article count)
- Send one **embed message** per article (journal, authors, date, AI summary, DOI link)
- Add 1 second delay between messages to respect Discord rate limits
- Handle Discord 429 (rate limit) errors dynamically by waiting for the specified `Retry-After` duration

### Module 5 — Database
- Track all fetched articles (PMID, DOI, title, journal, date)
- Track sent status per article
- Simple logs table for run history

### Module 6 — Main Orchestrator
- Called by cron job once per day
- Calls all modules in order: Fetch → Deduplicate → Summarize → Send
- Writes logs to file
- Exits cleanly after completion (no persistent process)

## 6. Project Folder Structure
```
research-digest-bot/
│
├── main.py                  ← Entry point, orchestrates everything
├── config.py                ← All settings loaded from .env
│
├── fetchers/
│   ├── pubmed.py            ← PubMed search + fetch logic
│   └── europepmc.py         ← Backup fetcher (optional, phase 2)
│
├── processors/
│   └── filter.py            ← Deduplication + article type filtering
│
├── summarizer/
│   └── llm.py               ← LLM API calls (Groq / Gemini / OpenAI)
│
├── notifier/
│   └── discord.py           ← Discord webhook logic
│
├── database/
│   └── db.py                ← All SQLite read/write operations
│
├── digest.db                ← SQLite database (auto-created)
├── bot.log                  ← Log file (auto-created)
├── .env                     ← Secrets (never commit this)
├── .env.example             ← Template for .env
└── requirements.txt
```

## 7. Database Schema

### Table: `articles`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto increment |
| pmid | TEXT UNIQUE | PubMed ID, used for deduplication |
| doi | TEXT | For article link |
| title | TEXT | |
| journal | TEXT | |
| pub_date | TEXT | |
| fetched_at | DATETIME | Auto timestamp |
| sent | INTEGER | 0 = not sent, 1 = sent |

### Table: `run_logs`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| run_date | TEXT | Date of the run |
| articles_found | INTEGER | |
| articles_sent | INTEGER | |
| status | TEXT | success / partial / failed |
| created_at | DATETIME | |

## 8. LLM Summary Format

The prompt will instruct the LLM to return a summary with these sections, every time, in consistent format:

1. **Key Finding** — 3-5 sentences, the most important result
2. **Study Design** — Study type, population, method (brief)
3. **Main Results** — Max 5 bullet points
4. **Clinical Relevance** — Why this matters for allergists/immunologists
5. **Limitations** — Max 2 lines, only if mentioned in abstract

Target length: **under 400 words** per summary

## 9. LLM Provider Options

| Provider | Model | Free Tier | Recommended Use |
|---|---|---|---|
| **Google Gemini** | gemini-2.5-flash | - | Main driver |
| **Openrouter** | gpt-5.4-mini | - | Backup |

## 10. Scheduling & Deployment

### Cron Job Approach (Recommended)
- Run once daily — suggested time **7:00–8:00 AM** server time
- Process starts, runs, exits — no persistent memory usage
- Estimated RAM during run: **50–80 MB**
- Estimated run time: **2–5 minutes** depending on article count

### Environment Variables Needed
```
NCBI_API_KEY
LLM_PROVIDER
LLM_API_KEY
LLM_MODEL
DISCORD_WEBHOOK_URL
LOOKBACK_DAYS        ← default: 1
MAX_ARTICLES_PER_RUN ← default: 10
```

## 11. Error Handling Strategy

| Scenario | Behavior |
|---|---|
| PubMed API down | Log error, exit gracefully, notify in Discord |
| Article has no abstract | Skip that article, continue with others |
| LLM API fails on one article | Skip summarization, still send article to Discord with "Summary unavailable" and notify in Discord |
| Discord webhook fails | Wait dynamically based on `Retry-After` header |
| Article already in DB | Skip silently |
| Zero articles found | Send a short "No new articles today" message to Discord |