# Design Document — Skill-Bridge Career Navigator

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Frontend | Streamlit | UI, dashboard rendering, audio UX |
| Backend | Flask | API endpoints, Gemini orchestration |
| Database | PostgreSQL | Mentee CRUD storage |
| AI | Gemini | Skills extraction, MCQs, gap analysis, career guidance |
| Fallback | Rule-based engine | Keyword extraction + template advice when Gemini is unavailable |

---

## Architecture & Data Flow

```
User (Streamlit UI)
      │
      │  resume text + target role + user intent
      ▼
Flask Backend
      │
      ├─► Gemini API ──► extract skills, identify gaps, generate roadmap advice
      │
      ├─► PostgreSQL ──► read/write mentee profile & session data
      │
      ├─► job_descriptions_500.csv ──► look up required skills + salary range for target role
      │
      └─► skills_learning_roadmap.csv ──► filter roadmap rows matching missing skills
      │
      │  JSON response (gaps, roadmap, MCQs, guidance)
      ▼
Streamlit UI
      │
      ├─► renders skill gap dashboard
      └─► renders mock interview + career guidance panel
```

**Step-by-step flow:**

1. The UI collects the mentee's resume-like input and target role, then sends it to the Flask backend.
2. The backend calls Gemini to extract skills from the input and identify gaps against the job description's `required_skills`.
3. The backend filters `skills_learning_roadmap.csv` to rows matching the missing skills, building a personalised learning plan.
4. Gemini generates MCQ questions, career pivot advice, and guidance text.
5. The backend returns a single JSON response to the UI.
6. Streamlit renders the dashboard, roadmap, and mock interview panel.

---

## AI Design & Fallback Strategy

### AI capabilities used

- **Skill extraction** — Gemini parses free-form resume text and returns a structured list of current skills.
- **Gap analysis** — Gemini compares extracted skills against the target role's required skills and ranks gaps by priority.
- **MCQ generation** — Gemini generates role-relevant multiple-choice questions for the mock interview flow.
- **Career guidance** — Gemini produces natural-language advice for career pivots and next steps.
- **Real-time audio** *(where supported)* — Gemini Live handles voice-based interaction for the pivot/interview flow.

### What "fallback" means in this codebase

When the Gemini API key is missing, the API is unreachable, or the model returns an invalid/empty response, the backend switches automatically to a rule-based fallback:

- **Skill extraction fallback** — a curated keyword list scans the resume text directly and returns matched skills. No model call is made.
- **Gap analysis fallback** — a simple set difference between extracted keywords and the job description's `required_skills` column produces the gap list.
- **Guidance fallback** — pre-written template advice strings are returned, keyed by role level and gap severity.
- **MCQ fallback** — a static question bank filtered by role category is used instead of generated questions.

The fallback path is triggered by catching `APIError`, `TimeoutError`, and empty-response conditions, and always returns the same JSON shape as the live path — so the UI never crashes or receives `null`.

### Why fallback improves robustness

- **No hard crashes** — every AI call is wrapped in a try/except; the app always returns a usable response.
- **Clear error signalling** — the JSON response includes a `source` field (`"gemini"` or `"fallback"`) and a human-readable `notice` string so the UI can inform the user transparently.
- **Reduced risk of bad guidance** — template advice is conservative and reviewed, reducing the chance of confidently wrong output when the model is unavailable.
- **Testability** — the fallback path is independently testable without any API key, which is why `pytest test_mentees.py` runs cleanly in any environment.

---

## Security & Responsible AI

### API key & secrets handling

- All secrets (`GEMINI_API_KEY`, database credentials) live exclusively in `.env`, which is listed in `.gitignore` and never committed.
- `.env.example` ships with placeholder values only — no real credentials are ever stored in the repository.
- The Flask backend reads secrets via `python-dotenv` at startup; they are never logged or exposed in API responses.

### Responsible AI considerations

- **Synthetic data only** — no real user profiles, resumes, or personal data are used anywhere in the project (see Dataset section below).
- **Output transparency** — every AI-generated response includes a `source` field so downstream consumers know whether the output came from Gemini or the fallback engine.
- **Stated limitations** — AI output may be imperfect; skill extraction can miss context-specific terms, and roadmap suggestions depend on CSV coverage. The fallback layer reduces the risk of incorrect or empty guidance reaching the user, but human review of career advice is always recommended.
- **No model fine-tuning on personal data** — the app uses Gemini via its public API with zero retention of user inputs beyond the current session.

---

## Datasets

All data files shipped in this repository are **fully synthetic** — no scraping, no personal data, no real job postings.

### `job_descriptions_500.csv`

| Property | Detail |
|----------|--------|
| Purpose | Provides "target role requirements" for gap analysis |
| Key columns used | `required_skills`, `salary_range`, `role_level`, `job_title` |
| How the app uses it | The backend filters rows by `job_title` and `role_level` matching the mentee's target role, then reads `required_skills` to compute the skill gap |
| Data origin | Synthetically generated — no real job postings, no scraped content |

### `skills_learning_roadmap.csv`

| Property | Detail |
|----------|--------|
| Purpose | Provides learning plan entries mapped to specific skills |
| Key columns used | `skill`, `resource_type`, `resource_name`, `estimated_hours`, `level` |
| How the app uses it | After gap analysis, the backend filters rows where `skill` matches any missing skill, then returns the filtered set as the mentee's personalised roadmap |
| Data origin | Synthetically curated — no third-party scraping |

### Mentee seed data *(if applicable)*

Any sample mentee JSON or CSV shipped in the repository contains entirely fictional profiles (randomly generated names, roles, and skill sets). This data is used only to demonstrate the CRUD flow and pre-populate the UI for reviewers — it contains no real personal information.

### Data usage summary

- **No scraping** — all CSV files were generated programmatically for this prototype.
- **No personal data** — no real names, emails, or resumes exist anywhere in the repo.
- **Lookup pattern** — the app performs in-memory CSV lookups (role → required skills → roadmap rows). No external data sources are queried at runtime beyond the Gemini API.
