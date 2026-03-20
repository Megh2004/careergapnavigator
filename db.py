"""
db.py — PostgreSQL connection and schema bootstrap for SkillGapBuilder.

Reads connection settings from environment variables:
  DATABASE_URL  (full DSN, e.g. postgresql://user:pass@host/dbname)
  or individually:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

Schema:
  mentees table — stores mentor's mentees with JSONB columns for skills / tasks.
"""

import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ── Connection factory ─────────────────────────────────────────────────────────

def get_connection():
    """Return a new psycopg2 connection using env vars."""
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "skillgapbuilder"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ── Schema bootstrap ───────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mentees (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(120)  NOT NULL,
    target      VARCHAR(200)  NOT NULL,
    category    VARCHAR(20)   NOT NULL CHECK (category IN ('Fresher', 'Switcher')),
    progress    SMALLINT      NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    skills      JSONB         NOT NULL DEFAULT '[]'::jsonb,
    tasks       JSONB         NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- auto-update updated_at on any UPDATE
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_mentees_updated_at ON mentees;
CREATE TRIGGER trg_mentees_updated_at
    BEFORE UPDATE ON mentees
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

_SYNTHETIC_MENTEES: list[dict] = [
    {
        "name": "Aarav Mehta",
        "target": "Backend Engineer",
        "category": "Fresher",
        "progress": 18,
        "skills": ["Python", "FastAPI", "PostgreSQL", "REST APIs", "Docker"],
        "tasks": [
            {"title": "Build a CRUD API with FastAPI", "done": True},
            {"title": "Add integration tests (pytest)", "done": False},
            {"title": "Ship a Dockerized version with health check", "done": False},
        ],
    },
    {
        "name": "Sana Khan",
        "target": "Data Analyst",
        "category": "Fresher",
        "progress": 32,
        "skills": ["SQL", "Python", "Pandas", "Excel", "Data Visualization"],
        "tasks": [
            {"title": "Clean a dataset and document assumptions", "done": True},
            {"title": "Create 3 dashboards (KPI + trends)", "done": False},
            {"title": "Write a short insights memo for stakeholders", "done": False},
        ],
    },
    {
        "name": "Rohan Verma",
        "target": "Frontend Developer",
        "category": "Fresher",
        "progress": 24,
        "skills": ["JavaScript", "React", "TypeScript", "CSS", "REST API"],
        "tasks": [
            {"title": "Implement a responsive React UI (no templates)", "done": True},
            {"title": "Add form validation + error states", "done": False},
            {"title": "Connect UI to a real API endpoint", "done": False},
        ],
    },
    {
        "name": "Mei Chen",
        "target": "Cloud Engineer",
        "category": "Fresher",
        "progress": 40,
        "skills": ["AWS", "Docker", "Kubernetes", "Linux", "CI/CD Basics"],
        "tasks": [
            {"title": "Containerize a small service and deploy it", "done": True},
            {"title": "Set up a basic CI pipeline (build + test)", "done": False},
            {"title": "Deploy on a managed cluster with monitoring", "done": False},
        ],
    },
    {
        "name": "Diego Morales",
        "target": "QA Engineer",
        "category": "Fresher",
        "progress": 12,
        "skills": ["Python", "Selenium", "REST APIs", "Test Plans", "Bug Reporting"],
        "tasks": [
            {"title": "Write a test plan for a sample web app", "done": True},
            {"title": "Automate 10 smoke tests with Selenium", "done": False},
            {"title": "Document edge cases and expected results", "done": False},
        ],
    },
    {
        "name": "Priyanka Das",
        "target": "DevOps Engineer",
        "category": "Switcher",
        "progress": 45,
        "skills": ["Linux", "Bash", "Docker", "Terraform", "CI/CD"],
        "tasks": [
            {"title": "Provision infrastructure with Terraform modules", "done": True},
            {"title": "Set up CI/CD for infra changes (safe rollout)", "done": False},
            {"title": "Create a runbook for common incidents", "done": False},
        ],
    },
    {
        "name": "Noah Williams",
        "target": "Machine Learning Engineer",
        "category": "Switcher",
        "progress": 28,
        "skills": ["Python", "PyTorch", "Feature Engineering", "Model Evaluation", "APIs"],
        "tasks": [
            {"title": "Train a baseline model and log metrics", "done": True},
            {"title": "Build a small inference API around the model", "done": False},
            {"title": "Write an evaluation report (what worked and why)", "done": False},
        ],
    },
    {
        "name": "Amina Hassan",
        "target": "Software Engineer (Full Stack)",
        "category": "Switcher",
        "progress": 36,
        "skills": ["JavaScript", "Node.js", "Express", "PostgreSQL", "React"],
        "tasks": [
            {"title": "Design DB schema and relationships", "done": True},
            {"title": "Add auth + protected routes", "done": False},
            {"title": "Implement search + pagination for data lists", "done": False},
        ],
    },
    {
        "name": "Ethan Brooks",
        "target": "Product Analyst",
        "category": "Switcher",
        "progress": 22,
        "skills": ["SQL", "Analytics", "Python", "A/B Testing", "Dashboards"],
        "tasks": [
            {"title": "Define a clear metric and success criteria", "done": False},
            {"title": "Run an analysis on funnel + retention", "done": False},
            {"title": "Present findings with a concise story", "done": False},
        ],
    },
    {
        "name": "Zara El-Amin",
        "target": "Security Analyst",
        "category": "Switcher",
        "progress": 15,
        "skills": ["Networking", "Linux", "OWASP", "Logging", "Threat Modeling"],
        "tasks": [
            {"title": "Do a basic threat model for a web app", "done": True},
            {"title": "Review logs and write incident notes", "done": False},
            {"title": "Fix a small vulnerability in a sandbox app", "done": False},
        ],
    },
]


def seed_synthetic_mentees() -> None:
    """
    Seed 10 synthetic mentees into the `mentees` table.

    Idempotent by name: if a seeded mentee name already exists, it is skipped.
    """
    if not _SYNTHETIC_MENTEES:
        return

    conn = get_connection()
    try:
        synthetic_names = [m["name"] for m in _SYNTHETIC_MENTEES]
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM mentees WHERE name = ANY(%s)",
                    (synthetic_names,),
                )
                existing = {row[0] for row in cur.fetchall()}

                inserted = 0
                for m in _SYNTHETIC_MENTEES:
                    if m["name"] in existing:
                        continue

                    cur.execute(
                        """
                        INSERT INTO mentees (name, target, category, progress, skills, tasks)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            m["name"],
                            m["target"],
                            m["category"],
                            int(m["progress"]),
                            json.dumps(m["skills"]),
                            json.dumps(m["tasks"]),
                        ),
                    )
                    inserted += 1

                if inserted:
                    print(f"[DB] Seeded synthetic mentees: inserted={inserted}.")
                else:
                    print("[DB] Synthetic mentees already present; skipping seeding.")
    except Exception as e:
        # Never fail app startup due to demo data seeding.
        print(f"[WARNING] Synthetic mentee seeding failed: {e}")
    finally:
        conn.close()


def init_db():
    """Create the mentees table (and trigger) if they don't already exist."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)
        print("[DB] Schema initialised (mentees table ready).")
    finally:
        conn.close()

    # Populate demo data for the mentor dashboard.
    try:
        seed_synthetic_mentees()
    except Exception as _e:
        # Best-effort only.
        pass


# ── Row → dict helper ──────────────────────────────────────────────────────────

def row_to_dict(row, cursor_description) -> dict:
    """Convert a psycopg2 row tuple + cursor description to a plain dict."""
    cols = [desc[0] for desc in cursor_description]
    d = dict(zip(cols, row))
    # Serialise UUID and datetime fields to strings for JSON
    for k, v in d.items():
        if hasattr(v, "isoformat"):       # datetime / date
            d[k] = v.isoformat()
        elif hasattr(v, "hex"):           # UUID
            d[k] = str(v)
    # JSONB columns come back as Python objects already via psycopg2 extras
    return d


# ── CRUD helpers ───────────────────────────────────────────────────────────────

def db_list_mentees(q="", category="", min_progress=None, max_progress=None,
                    sort_by="name_asc") -> list[dict]:
    """Return a filtered + sorted list of mentees from PostgreSQL."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions = []
            params: list = []

            if q:
                conditions.append(
                    "(name ILIKE %s OR target ILIKE %s OR skills::text ILIKE %s)"
                )
                like = f"%{q}%"
                params += [like, like, like]

            if category:
                conditions.append("category = %s")
                params.append(category)

            if min_progress is not None:
                conditions.append("progress >= %s")
                params.append(min_progress)

            if max_progress is not None:
                conditions.append("progress <= %s")
                params.append(max_progress)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            order_map = {
                "progress_asc":  "progress ASC,  name ASC",
                "progress_desc": "progress DESC, name ASC",
                "name_desc":     "name DESC",
                "name_asc":      "name ASC",
            }
            order = order_map.get(sort_by, "name ASC")

            cur.execute(f"SELECT * FROM mentees {where} ORDER BY {order}", params)
            rows = cur.fetchall()
            return [_realdict_to_plain(r) for r in rows]
    finally:
        conn.close()


def db_get_mentee(mentee_id: str) -> dict | None:
    """Fetch a single mentee by UUID string; returns None if not found."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM mentees WHERE id = %s", (mentee_id,))
            row = cur.fetchone()
            return _realdict_to_plain(row) if row else None
    finally:
        conn.close()


def db_create_mentee(name: str, target: str, category: str,
                     progress: int = 0, skills: list = None,
                     tasks: list = None) -> dict:
    """Insert a new mentee row and return the full record."""
    skills = skills or []
    tasks  = tasks  or []
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO mentees (name, target, category, progress, skills, tasks)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (name, target, category, progress,
                     json.dumps(skills), json.dumps(tasks))
                )
                row = cur.fetchone()
                return _realdict_to_plain(row)
    finally:
        conn.close()


def db_update_mentee(mentee_id: str, updates: dict) -> dict | None:
    """Apply a partial update dict to a mentee row; returns updated record or None."""
    allowed = {"name", "target", "category", "progress", "skills", "tasks"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return db_get_mentee(mentee_id)

    # Serialise list fields to JSON strings for psycopg2
    for k in ("skills", "tasks"):
        if k in filtered:
            filtered[k] = json.dumps(filtered[k])

    set_clause = ", ".join(f"{k} = %s" for k in filtered)
    params = list(filtered.values()) + [mentee_id]

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"UPDATE mentees SET {set_clause} WHERE id = %s RETURNING *",
                    params
                )
                row = cur.fetchone()
                return _realdict_to_plain(row) if row else None
    finally:
        conn.close()


def db_delete_mentee(mentee_id: str) -> bool:
    """Delete a mentee by UUID. Returns True if a row was deleted."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM mentees WHERE id = %s", (mentee_id,))
                return cur.rowcount > 0
    finally:
        conn.close()


# ── Internal helper ────────────────────────────────────────────────────────────

def _realdict_to_plain(row) -> dict:
    """Convert a psycopg2 RealDictRow to a plain JSON-serialisable dict."""
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "hex"):   # UUID type
            d[k] = str(v)
    return d
