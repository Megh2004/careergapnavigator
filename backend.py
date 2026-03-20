import os
import json
import re
import csv
import io
import uuid
import asyncio
import threading
import PyPDF2
import base64
from datetime import datetime
from flask import Flask, request, jsonify
from google import genai
from google.genai import types
from dotenv import load_dotenv
from db import (
    init_db,
    db_list_mentees,
    db_get_mentee,
    db_create_mentee,
    db_update_mentee,
    db_delete_mentee,
)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = Flask(__name__)

# ── Init PostgreSQL schema on startup ─────────────────────────────────────────
try:
    init_db()
except Exception as _db_err:
    print(f"[WARNING] Could not initialise PostgreSQL: {_db_err}\n"
          "         Mentee endpoints will return 503 until the DB is reachable.")


# ══════════════════════════════════════════════════════════════════════════════
# ── Input Validation Helpers ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

VALID_CATEGORIES = ("Fresher", "Switcher")
VALID_SORT_OPTIONS = ("name_asc", "name_desc", "progress_asc", "progress_desc")


def _validate_mentee_payload(data: dict, partial: bool = False) -> list[str]:
    """
    Validate a mentee creation or partial-update payload.

    Args:
        data:    The parsed JSON body.
        partial: If True, only validate fields that are present (for PUT/PATCH).

    Returns:
        A list of human-readable error strings (empty = valid).
    """
    errors: list[str] = []

    # ── name ──
    if "name" in data or not partial:
        name = data.get("name", "")
        if not isinstance(name, str):
            errors.append("'name' must be a string.")
        elif not name.strip():
            errors.append("'name' is required and cannot be blank.")
        elif len(name.strip()) < 2:
            errors.append("'name' must be at least 2 characters long.")
        elif len(name.strip()) > 120:
            errors.append("'name' must not exceed 120 characters.")

    # ── target ──
    if "target" in data or not partial:
        target = data.get("target", "")
        if not isinstance(target, str):
            errors.append("'target' must be a string.")
        elif not target.strip():
            errors.append("'target' (role) is required and cannot be blank.")
        elif len(target.strip()) < 2:
            errors.append("'target' must be at least 2 characters long.")
        elif len(target.strip()) > 200:
            errors.append("'target' must not exceed 200 characters.")

    # ── category ──
    if "category" in data or not partial:
        category = data.get("category", "")
        if not isinstance(category, str):
            errors.append("'category' must be a string.")
        elif category not in VALID_CATEGORIES:
            errors.append(
                f"'category' must be one of: {', '.join(VALID_CATEGORIES)}. "
                f"Got: '{category}'."
            )

    # ── progress ──
    if "progress" in data:
        progress = data["progress"]
        if not isinstance(progress, int):
            try:
                progress = int(progress)
            except (ValueError, TypeError):
                errors.append("'progress' must be an integer between 0 and 100.")
                progress = None
        if progress is not None and not (0 <= progress <= 100):
            errors.append(
                f"'progress' must be between 0 and 100. Got: {progress}."
            )

    # ── skills ──
    if "skills" in data:
        skills = data["skills"]
        if not isinstance(skills, list):
            errors.append("'skills' must be a JSON array of strings.")
        else:
            bad = [s for s in skills if not isinstance(s, str)]
            if bad:
                errors.append(
                    f"'skills' array items must all be strings. "
                    f"Found non-string item(s): {bad[:3]}."
                )
            elif len(skills) > 50:
                errors.append("'skills' array must contain at most 50 items.")

    # ── tasks ──
    if "tasks" in data:
        tasks = data["tasks"]
        if not isinstance(tasks, list):
            errors.append("'tasks' must be a JSON array of objects.")
        else:
            for i, t in enumerate(tasks):
                if not isinstance(t, dict):
                    errors.append(f"'tasks[{i}]' must be an object with 'title' and 'done' fields.")
                    continue
                if not t.get("title") or not isinstance(t.get("title"), str):
                    errors.append(f"'tasks[{i}].title' must be a non-empty string.")
                if "done" in t and not isinstance(t["done"], bool):
                    errors.append(f"'tasks[{i}].done' must be a boolean (true/false).")
            if len(tasks) > 30:
                errors.append("'tasks' array must contain at most 30 items.")

    return errors



# ══════════════════════════════════════════════════════════════════════════════
# ── Rule-Based / Manual Fallbacks ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# A master keyword list used when Gemini is unavailable for skill extraction
_KNOWN_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust",
    "Swift", "Kotlin", "Ruby", "PHP", "Scala", "R", "Dart", "Perl",
    "HTML", "CSS", "SQL", "NoSQL", "Bash", "Shell",
    "React", "Angular", "Vue", "Next.js", "Svelte", "Node.js", "Express",
    "Django", "Flask", "FastAPI", "Spring Boot", "Rails",
    "TensorFlow", "PyTorch", "Keras", "Scikit-Learn", "OpenCV",
    "Pandas", "NumPy", "Matplotlib", "Seaborn",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform",
    "Jenkins", "CI/CD", "GitHub Actions", "Ansible",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
    "Spark", "Kafka", "Airflow", "dbt", "Snowflake", "BigQuery",
    "Git", "Linux", "REST", "GraphQL", "gRPC",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
    "System Design", "Distributed Systems", "Microservices",
    "Agile", "Scrum", "JIRA", "Figma", "Tableau", "Power BI",
    "MLOps", "Data Pipelines", "ETL", "Data Analysis",
    "Transformers", "LLM", "RAG", "LangChain",
    "Financial Modelling", "Statistics", "Looker",
    "Product Roadmapping", "UX Research", "Analytics",
]

def _fallback_extract_skills(text: str) -> list:
    """Keyword-matching fallback when Gemini is unavailable."""
    text_lower = text.lower()
    found = []
    for skill in _KNOWN_SKILLS:
        # Check for the skill as a whole word (case-insensitive)
        pattern = r'\b' + re.escape(skill.lower()) + r'\b'
        if re.search(pattern, text_lower):
            found.append(skill)
    return found


_FALLBACK_MCQS = {
    "Python": [
        {"question": "What is the output of `len([1, [2, 3], 4])`?", "skill": "Python",
         "options": {"A": "3", "B": "4", "C": "5", "D": "Error"}, "answer": "A"},
        {"question": "Which keyword is used to handle exceptions in Python?", "skill": "Python",
         "options": {"A": "catch", "B": "except", "C": "handle", "D": "rescue"}, "answer": "B"},
    ],
    "SQL": [
        {"question": "Which SQL clause is used to filter groups?", "skill": "SQL",
         "options": {"A": "WHERE", "B": "HAVING", "C": "GROUP BY", "D": "ORDER BY"}, "answer": "B"},
        {"question": "What does INNER JOIN return?", "skill": "SQL",
         "options": {"A": "All rows from both tables", "B": "Only matching rows",
                     "C": "All rows from left table", "D": "All rows from right table"}, "answer": "B"},
    ],
    "JavaScript": [
        {"question": "What is the result of `typeof null` in JavaScript?", "skill": "JavaScript",
         "options": {"A": "'null'", "B": "'undefined'", "C": "'object'", "D": "'boolean'"}, "answer": "C"},
        {"question": "Which method converts a JSON string to an object?", "skill": "JavaScript",
         "options": {"A": "JSON.stringify()", "B": "JSON.parse()", "C": "JSON.convert()", "D": "JSON.decode()"}, "answer": "B"},
    ],
    "_generic": [
        {"question": "What does REST stand for?", "skill": "General",
         "options": {"A": "Representational State Transfer", "B": "Remote Execution Standard Transfer",
                     "C": "Reliable Efficient Secure Technology", "D": "None of the above"}, "answer": "A"},
        {"question": "In version control, what does a 'merge conflict' indicate?", "skill": "Git",
         "options": {"A": "The repository is corrupted", "B": "Two branches modified the same lines",
                     "C": "A file was deleted", "D": "The remote is unreachable"}, "answer": "B"},
    ],
}

def _fallback_generate_mcqs(skills: list, count: int = 10) -> list:
    """Template-based MCQ generation when Gemini is unavailable."""
    mcqs = []
    for skill in skills:
        mcqs.extend(_FALLBACK_MCQS.get(skill, []))
    mcqs.extend(_FALLBACK_MCQS["_generic"])
    # De-duplicate by question text
    seen = set()
    unique = []
    for q in mcqs:
        if q["question"] not in seen:
            seen.add(q["question"])
            unique.append(q)
    return unique[:count]


def _fallback_rate_skills(skills: list) -> dict:
    """Heuristic: assign 3 (Intermediate) to every skill when Gemini is unavailable."""
    return {s: 3 for s in skills}


def _fallback_career_advice(missing_skills: list, matching_skills: list, score: int = 0, total: int = 0) -> dict:
    """Rule-based career advice when Gemini is unavailable."""
    n_miss = len(missing_skills)
    n_match = len(matching_skills)
    total_skills = n_miss + n_match
    readiness = int((n_match / total_skills) * 100) if total_skills > 0 else 0
    if score and total:
        readiness = min(readiness, int((score / total) * 100))

    roadmap = []
    for i, s in enumerate(missing_skills[:5]):
        roadmap.append(f"Week {i+1}-{i+2}: Study {s} fundamentals via free online courses (Coursera / YouTube).")
    if not roadmap:
        roadmap = ["You have all the core skills. Focus on building portfolio projects."]

    fastest = (
        "Focus on the top 3 missing skills first. Use project-based learning: "
        "build a small project for each skill, then contribute to open-source repos."
    )
    return {
        "readiness_score": readiness,
        "transferable_analysis": f"You have {n_match} of {total_skills} required skills. "
                                  f"Your existing skills provide a solid foundation to learn the remaining {n_miss}.",
        "missing_skills": missing_skills,
        "learning_roadmap": roadmap,
        "fastest_way_to_learn": fastest,
    }


def _fallback_guide_tip(user_major: str, guide_name: str, guide_role: str) -> str:
    """Template-based networking tip when Gemini is unavailable."""
    return (
        f"Reach out to {guide_name} with a brief intro about your {user_major} background "
        f"and ask how they broke into the {guide_role} role. "
        f"People love sharing their journey — keep your first message short and specific!"
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── Gemini: text prompt (with fallback) ────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
def gemini_text(prompt: str) -> str:
    """Send a text-only prompt to Gemini and return raw response text.
    Returns empty string on failure — callers should check and use fallbacks."""
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not set. Using fallback.")
        return ""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model="gemma-3-27b-it",
            contents=prompt
        )
        return resp.text.strip()
    except Exception as e:
        print(f"Gemini text error: {e}  — falling back to rule-based logic.")
        return ""


# ── Gemini: native PDF parsing ─────────────────────────────────────────────────
def parse_pdf_with_gemini(pdf_bytes: bytes) -> str:
    """Pass raw PDF bytes natively to Gemini and extract structured resume info."""
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not set. Cannot parse PDF.")
        return ""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "You are an expert technical recruiter and resume parser.\n"
            "I have attached a candidate's resume in PDF format.\n"
            "Read it carefully and extract the following 4 sections in plain text:\n"
            "1. Skills (list all technical skills, tools, frameworks, languages)\n"
            "2. Experience (job titles, companies, durations, responsibilities)\n"
            "3. Projects (name, description, tech used)\n"
            "4. Certifications\n\n"
            "Return only the structured plain-text output. "
            "If a section is missing, write 'None found.'"
        )
        resp = client.models.generate_content(
            model="gemma-3-27b-it",
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                prompt
            ]
        )
        print("\n" + "="*50)
        print(" Gemini PDF Parse Result:")
        print("="*50)
        print(resp.text)
        print("="*50 + "\n")
        return resp.text.strip()
    except Exception as e:
        print(f"Gemini PDF parse error: {e}")
        return ""


# ── Gemini: extract skills list from parsed text ───────────────────────────────
def extract_skills_from_text(parsed_text: str) -> list:
    """From Gemini-parsed resume text, extract a JSON list of technical skills.
    Falls back to keyword matching if Gemini is unavailable or returns bad data."""
    prompt = (
        f"From the resume text below, extract ONLY technical skills "
        f"(languages, frameworks, tools, databases, cloud platforms, etc.).\n\n"
        f"Resume:\n{parsed_text[:4000]}\n\n"
        f"Return a JSON array of skill strings ONLY. No markdown, no explanation.\n"
        f'Example: ["Python", "React", "AWS"]'
    )
    raw = gemini_text(prompt)
    skills = parse_json_safe(raw)
    if isinstance(skills, list) and skills:
        return [str(s) for s in skills]
    # ── Fallback: keyword-based extraction ──
    print("Using fallback keyword-based skill extraction.")
    return _fallback_extract_skills(parsed_text)


# ── JSON parser ────────────────────────────────────────────────────────────────
def parse_json_safe(text: str):
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'[\{\[].*[\}\]]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None


# ── Generate 20 MCQs ───────────────────────────────────────────────────────────
def generate_mcqs(skills: list, count: int = 10, context: str = "") -> list:
    """Generate MCQs via Gemini.  Falls back to template bank if AI fails."""
    skills_str = ", ".join(skills[:15])
    prompt = (
        f"You are a technical interviewer. Generate exactly {count} MCQs "
        f"testing these skills: {skills_str}.\n"
        f"{context}\n\n"
        f"Each question must have exactly 4 options (A, B, C, D) and one correct answer.\n\n"
        f"Return ONLY a valid JSON array:\n"
        f'[\n  {{"question": "...", "skill": "...", '
        f'"options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "answer": "A"}}\n]\n'
        f"No markdown, no preamble."
    )
    raw = gemini_text(prompt)
    mcqs = parse_json_safe(raw)
    if isinstance(mcqs, list) and mcqs:
        return mcqs
    # ── Fallback: template MCQ bank ──
    print("Using fallback template MCQ generation.")
    return _fallback_generate_mcqs(skills, count)


# ── Rate skills 1–5 ────────────────────────────────────────────────────────────
def rate_skills_with_gemini(skills: list, mcqs: list) -> dict:
    """Rate skills via Gemini.  Falls back to flat 3/5 for every skill."""
    mcq_summary = json.dumps(mcqs[:20], indent=2)
    skills_str = ", ".join(skills)
    prompt = (
        f"You are a senior technical assessor. Based on these skills: {skills_str}\n"
        f"and these MCQs:\n{mcq_summary}\n\n"
        f"Rate each skill 1–5:\n"
        f"1=Beginner, 2=Basic, 3=Intermediate, 4=Advanced, 5=Expert\n\n"
        f"Return ONLY a JSON object: {{\"Python\": 4, \"React\": 3, ...}}\n"
        f"No markdown, no preamble."
    )
    raw = gemini_text(prompt)
    ratings = parse_json_safe(raw)
    if isinstance(ratings, dict) and ratings:
        return {k: max(1, min(5, int(v))) for k, v in ratings.items()}
    # ── Fallback: default intermediate rating ──
    print("Using fallback heuristic skill rating (3/5 for all).")
    return _fallback_rate_skills(skills)


# ── Helper: get PDF bytes from request ─────────────────────────────────────────
def get_pdf_bytes() -> bytes | None:
    """Extract PDF bytes from multipart upload field 'pdf'."""
    if "pdf" in request.files:
        f = request.files["pdf"]
        if f.filename:
            return f.read()
    return None

# ── Helper: get JD skills from CSV ─────────────────────────────────────────────
def get_jd_skills(target_role: str, target_exp: str) -> tuple[list, str]:
    """Find the best JD from CSV for the role and experience, and return its required skills and salary range."""
    if not os.path.exists("job_descriptions_500.csv"):
        return [], "N/A"

    try:
        exp_int = int(target_exp)
    except ValueError:
        exp_int = 0

    best_jd = None
    fallback_jd = None
    role_words = [w for w in target_role.lower().replace("dev", "developer").replace("eng", "engineer").split() if len(w) > 2]

    try:
        with open("job_descriptions_500.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    row_exp = int(row.get("years_experience", 0))
                except ValueError:
                    row_exp = 0
                
                if row_exp == exp_int:
                    if not fallback_jd:
                        fallback_jd = row
                    
                    row_title = row.get("title", "").lower()
                    if any(w in row_title for w in role_words) or target_role.lower() in row_title:
                        best_jd = row
                        break
            
            chosen_jd = best_jd or fallback_jd
            if chosen_jd:
                raw_skills = chosen_jd.get("required_skills", "")
                salary = chosen_jd.get("salary_range", "N/A")
                return [s.strip() for s in raw_skills.split(",") if s.strip()], salary
    except Exception as e:
        print(f"Error reading JD CSV: {e}")
    
    return [], "N/A"

def get_roadmap_for_skills(missing_skills: list, target_level: str = "Junior") -> list:
    """Fetch roadmap resources matching specific missing skills and seniority level."""
    roadmap_data = []
    if not missing_skills or not os.path.exists("skills_learning_roadmap.csv"):
        return roadmap_data
        
    missing_lower = [s.lower().strip() for s in missing_skills]
    try:
        with open("skills_learning_roadmap.csv", "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("level", "Junior").lower() == target_level.lower():
                    skill_val = row.get("skill", "").lower().strip()
                    if any(skill_val in m or m in skill_val for m in missing_lower):
                        item = {k: v for k, v in row.items() if k != "course_url"}
                        roadmap_data.append(item)
    except Exception as e:
        print(f"Error reading Roadmap CSV: {e}")
    return roadmap_data

def get_all_roadmap_data(target_role: str, years_of_experience: str) -> list:
    """Read the roadmap CSV and filter for entries that match the role and seniority level."""
    data = []
    if not os.path.exists("skills_learning_roadmap.csv"):
        return data

    # Map experience to level
    try:
        exp_int = int(years_of_experience)
    except ValueError:
        exp_int = 0
    
    level = "Junior"
    if exp_int >= 6: level = "Senior"
    elif exp_int >= 2: level = "Mid"
    
    role_words = [w for w in target_role.lower().split() if len(w) > 2]

    try:
        with open("skills_learning_roadmap.csv", "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_role = row.get("role", "").lower()
                row_level = row.get("level", "").lower()
                
                # Check level match
                if row_level != level.lower():
                    continue
                
                # Check role match (fuzzy)
                if any(w in row_role for w in role_words) or target_role.lower() in row_role:
                    data.append({k: v for k, v in row.items() if k != "course_url"})
        
    except Exception as e:
        print(f"Error reading Roadmap CSV for filtered data: {e}")
    
    return data[:80] # High precision limit to avoid noise


# ── /api/career-stage/fresher ──────────────────────────────────────────────────
@app.route('/api/career-stage/fresher', methods=['POST'])
def handle_fresher():
    """
    Accepts: multipart/form-data
      - pdf         (file, required) — raw PDF resume
      - target_role (field)
      - github_url  (field, optional)

    Pipeline:
      1. Parse PDF natively with Gemini
      2. Extract skills list
      3. Generate 20 beginner-level MCQs
      4. Rate each skill 1–5
    """
    target_role = request.form.get("target_role", "Unknown Role")
    resume_text = request.form.get("resume_text", "")
    github_url  = request.form.get("github_url", "")
    pdf_bytes   = get_pdf_bytes()

    if not pdf_bytes and not resume_text.strip():
        return jsonify({"error": "Either a PDF file or 'resume_text' is required."}), 400

    if pdf_bytes:
        # Local PDF text extraction using PyPDF2 (Python-based parsing)
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            parsed_text = ""
            for page in pdf_reader.pages:
                parsed_text += page.extract_text() or ""
            print("\n" + "="*50)
            print(" Local PDF Extraction (PyPDF2) for Fresher:")
            print("="*50)
            print(parsed_text[:2000] + "...")
            print("="*50 + "\n")
        except Exception as e:
            print(f"Local PDF extraction error (Fresher): {e}")
            return jsonify({"error": f"Local PDF extraction failed: {e}"}), 500
    else:
        parsed_text = resume_text

    # Step 2 – Extract skills
    skills = extract_skills_from_text(parsed_text)
    if not skills:
        return jsonify({"error": "No skills found in PDF."}), 500

    # Step 3 – Generate 10 high-quality MCQs
    mcqs = generate_mcqs(
        skills, count=10,
        context=(
            "The candidate is a fresher. Keep questions at an intermediate level. "
            "Ensure the questions are of very high quality, focusing on practical understanding, "
            "code comprehension, or logic rather than just basic trivia."
        )
    )

    # Step 4 – Rate each skill 1–5
    skill_ratings = rate_skills_with_gemini(skills, mcqs)

    return jsonify({
        "status": "success",
        "career_stage": "Fresher",
        "target_role": target_role,
        "parsed_resume_summary": parsed_text[:500] + "...",
        "extracted_skills": skills,
        "skill_ratings": skill_ratings,
        "mcqs": mcqs,
        "guidance": (
            "Focus on foundational skills, portfolio projects, and open-source contributions. "
            "Aim to push each skill rating to 4+ before applying."
        )
    })


# ── /api/career-stage/switcher ────────────────────────────────────────────────
@app.route('/api/career-stage/switcher', methods=['POST'])
def handle_switcher():
    """
    Accepts: multipart/form-data
      - pdf                 (file, required)
      - target_role         (field)
      - years_of_experience (field, required)
      - github_url          (field, optional)

    Pipeline: PDF parse → extract skills → 20 intermediate MCQs → rate 1–5
    """
    target_role         = request.form.get("target_role", "Unknown Role")
    resume_text         = request.form.get("resume_text", "")
    years_of_experience = request.form.get("years_of_experience", "")
    github_url          = request.form.get("github_url", "")
    pdf_bytes           = get_pdf_bytes()

    if not pdf_bytes and not resume_text.strip():
        return jsonify({"error": "Either a PDF file or 'resume_text' is required."}), 400
    if not years_of_experience:
        return jsonify({"error": "Missing 'years_of_experience' field."}), 400

    if pdf_bytes:
        # Local PDF text extraction using PyPDF2
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            parsed_text = ""
            for page in pdf_reader.pages:
                parsed_text += page.extract_text() or ""
            print("\n" + "="*50)
            print(" Local PDF Extraction (PyPDF2) for Switcher:")
            print("="*50)
            print(parsed_text[:2000] + "...") # Print first 2000 chars
            print("="*50 + "\n")
        except Exception as e:
            print(f"Local PDF extraction error: {e}")
            return jsonify({"error": f"Local PDF extraction failed: {e}"}), 500
    else:
        parsed_text = resume_text
    # Step 2 – Extract skills from locally parsed resume text (Call #1)
    skills_prompt = f"From the resume text below, extract technical skills targetting {target_role}.\\nResume:\\n{parsed_text[:4000]}\\nReturn JSON: {{'extracted_skills': ['s1', 's2']}}"
    raw_skills = gemini_text(skills_prompt)
    res_data = parse_json_safe(raw_skills)
    extracted_skills = res_data.get("extracted_skills", []) if isinstance(res_data, dict) else []
    
    if not extracted_skills:
        extracted_skills = extract_skills_from_text(parsed_text)

    # Step 3 - Compare with JD Skills (from CSV)
    jd_skills, avg_salary = get_jd_skills(target_role, years_of_experience)
    cv_lower = {s.lower().strip() for s in extracted_skills}
    missing_skills = [s for s in jd_skills if s.lower().strip() not in cv_lower]
    matching_skills = [s for s in jd_skills if s.lower().strip() in cv_lower]
    
    # Map experience to level
    try:
        exp_int = int(years_of_experience)
    except ValueError:
        exp_int = 0
    t_level = "Junior"
    if exp_int >= 6: t_level = "Senior"
    elif exp_int >= 2: t_level = "Mid"
    
    # Step 4 - Fetch roadmap items for MISSING skills only (Python logic)
    roadmap_items = get_roadmap_for_skills(missing_skills, t_level)
    
    # Step 5 - Final Analysis & Score (Call #2)
    final_prompt = f"""
    You are a career counseling expert.
    Analyze this transition to a {t_level} level {target_role} role.
    
    Target Requirements: {jd_skills}
    Candidate Existing Skills: {extracted_skills}
    Identified Missing Skills: {missing_skills}
    Available Learning Resources: {json.dumps(roadmap_items)}
    
    Please provide:
    1. A job readiness score (0-100%).
    2. A detailed transferable skills analysis (how existing experience helps).
    3. A clear list of missing skills.
    4. A concise learning roadmap (list of strings) derived STRICTLY from the Available Learning Resources.
    5. The fastest strategy to learn (fastest_way_to_learn).
    
    Return EXACT JSON: 
    'readiness_score' (int), 'transferable_analysis' (str), 'missing_skills' (list), 'learning_roadmap' (list of strings), 'fastest_way_to_learn' (str).
    """
    
    raw_analysis = gemini_text(final_prompt)
    analysis = parse_json_safe(raw_analysis)
    
    if not isinstance(analysis, dict) or not analysis:
        # ── Fallback: rule-based career advice ──
        print("Using fallback rule-based career advice for switcher.")
        analysis = _fallback_career_advice(missing_skills, matching_skills)

    return jsonify({
        "status": "success",
        "career_stage": "Switcher",
        "target_role": target_role,
        "gap_analysis": {
            "jd_skills_required": jd_skills,
            "avg_compensation": avg_salary,
            "matching_skills": matching_skills,
            "missing_skills": missing_skills,
            "gemini_advice": analysis
        }
    })


# ── /api/career-stage/mentor ──────────────────────────────────────────────────
@app.route('/api/career-stage/mentor', methods=['POST'])
def handle_mentor():
    """
    Accepts: multipart/form-data
      - pdf                     (file, required) — mentor's resume
      - target_role             (field)
      - mentee_category         (field, required) — 'Fresher' or 'Switcher'
      - mentee_years_experience (field, required if mentee_category == 'Switcher')
      - github_url              (field, optional)

    Pipeline: PDF parse → extract skills → 20 MCQs calibrated to mentee level → rate 1–5
    """
    target_role          = request.form.get("target_role", "Unknown Role")
    resume_text          = request.form.get("resume_text", "")
    mentee_category      = request.form.get("mentee_category")
    mentee_years_exp     = request.form.get("mentee_years_experience", "")
    github_url           = request.form.get("github_url", "")
    pdf_bytes            = get_pdf_bytes()

    if not pdf_bytes and not resume_text.strip():
        return jsonify({"error": "Either a PDF file or 'resume_text' is required."}), 400
    if not mentee_category:
        return jsonify({"error": "Missing 'mentee_category' field."}), 400
    if mentee_category == "Switcher" and not mentee_years_exp:
        return jsonify({"error": "Missing 'mentee_years_experience' for Switcher mentee."}), 400

    if pdf_bytes:
        parsed_text = parse_pdf_with_gemini(pdf_bytes)
        if not parsed_text:
            return jsonify({"error": "Gemini could not parse the PDF."}), 500
    else:
        parsed_text = resume_text

    skills = extract_skills_from_text(parsed_text)
    if not skills:
        return jsonify({"error": "No skills found in PDF."}), 500

    if mentee_category == "Fresher":
        context = (
            "Mentor is preparing for a FRESHER mentee. "
            "Generate beginner-to-intermediate questions for mock coaching sessions."
        )
    else:
        context = (
            f"Mentor is preparing for a SWITCHER mentee with {mentee_years_exp} years experience. "
            "Generate intermediate-to-advanced practical questions."
        )

    mcqs = generate_mcqs(skills, count=20, context=context)
    skill_ratings = rate_skills_with_gemini(skills, mcqs)

    return jsonify({
        "status": "success",
        "career_stage": "Mentor",
        "target_role": target_role,
        "mentee_category": mentee_category,
        "mentee_years_experience": mentee_years_exp if mentee_category == "Switcher" else None,
        "parsed_resume_summary": parsed_text[:500] + "...",
        "mentor_skills": skills,
        "mentor_skill_ratings": skill_ratings,
        "mentee_mcqs": mcqs,
        "guidance": (
            f"Use these MCQs in your mentee sessions. "
            f"Focus on skills rated 1–2 to close the biggest gaps fast."
        )
    })

# ── /api/career-stage/fresher/mock ─────────────────────────────────────────────
@app.route('/api/career-stage/fresher/mock', methods=['POST'])
def handle_fresher_mock():
    target_role = request.form.get("target_role", "Software Engineer")
    resume_text = request.form.get("resume_text", "")
    pdf_bytes = get_pdf_bytes()
    
    cv_skills = []
    if pdf_bytes:
        # Local PDF text extraction using PyPDF2 (Python-based parsing)
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            parsed_text = ""
            for page in pdf_reader.pages:
                parsed_text += page.extract_text() or ""
            print("\n" + "="*50)
            print(" Local PDF Extraction (PyPDF2) for Fresher Mock:")
            print("="*50)
            print(parsed_text[:2000] + "...")
            print("="*50 + "\n")
            cv_skills = extract_skills_from_text(parsed_text)
        except Exception as e:
            print(f"Local PDF extraction error (Fresher Mock): {e}")
            return jsonify({"error": f"Local PDF extraction failed: {e}"}), 500
    elif resume_text.strip():
        # fallback text
        prompt = f"Extract a concise list of skills from this resume targetting {target_role}.\\n{resume_text}\\nReturn JSON: {{'extracted_skills': ['s1', 's2']}}"
        raw_txt = gemini_text(prompt)
        res_data = parse_json_safe(raw_txt)
        if isinstance(res_data, dict):
            cv_skills = res_data.get("extracted_skills", [])
            
    # Get 0 YOE JD skills
    jd_skills, _ = get_jd_skills(target_role, "0")
    
    cv_lower = {s.lower() for s in cv_skills}
    missing_skills = [s for s in jd_skills if s.lower() not in cv_lower]
    
    prompt = f"""
    You are a rigorous technical interviewer for a {target_role} role. 
    The candidate has the following existing skills: {cv_skills}.
    They are currently missing the following standard skills: {missing_skills}.
    
    Based on their existing skills and the ones they are missing, please generate the 10 most important interview questions they should expect for this entry-level role.
    Ensure questions test core concepts of their existing skills, but also test behavioral/approach questions on how they would learn their missing skills.
    
    Return EXACTLY a pure JSON array containing 10 strings.
    Example:
    [
      "Can you explain how you used Python in your past projects?",
      "How would you approach learning React if assigned to a frontend task?",
      "..."
    ]
    """
    raw_questions = gemini_text(prompt)
    questions = parse_json_safe(raw_questions)
    if not isinstance(questions, list):
        questions = ["(Error generating questions. Please try again or re-upload your resume.)"]
        
    return jsonify({
        "status": "success",
        "mock_questions": questions[:10],
        "cv_skills": cv_skills,
        "missing_skills": missing_skills
    })


# ── /api/career-stage/switcher/mock ────────────────────────────────────────────
@app.route('/api/career-stage/switcher/mock', methods=['POST'])
def handle_switcher_mock():
    """
    Generate 10 tailored mock interview questions for a SWITCHER candidate
    based on their resume and the target role's JD skills.

    Accepts: multipart/form-data
      - pdf                 (file, optional) — candidate resume
      - resume_text         (field, optional) — plain-text resume
      - target_role         (field, required)
      - years_of_experience (field, required)
    """
    target_role = request.form.get("target_role", "Software Engineer")
    resume_text = request.form.get("resume_text", "")
    years_of_experience = request.form.get("years_of_experience", "")
    pdf_bytes = get_pdf_bytes()

    if not pdf_bytes and not resume_text.strip():
        return jsonify({"error": "Either a PDF file or 'resume_text' is required."}), 400
    if not years_of_experience:
        return jsonify({"error": "Missing 'years_of_experience' field."}), 400

    cv_skills: list[str] = []
    if pdf_bytes:
        # Local PDF parsing (same approach as main Switcher endpoint)
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            parsed_text = ""
            for page in pdf_reader.pages:
                parsed_text += page.extract_text() or ""
            print("\n" + "="*50)
            print(" Local PDF Extraction (PyPDF2) for Switcher Mock:")
            print("="*50)
            print(parsed_text[:2000] + "...")
            print("="*50 + "\n")
            cv_skills = extract_skills_from_text(parsed_text)
        except Exception as e:
            print(f"Local PDF extraction error (Switcher Mock): {e}")
            return jsonify({"error": f"Local PDF extraction failed: {e}"}), 500
    else:
        # Fallback: extract skills directly from provided text using Gemini
        prompt = (
            f"Extract a concise list of technical skills from this resume text, "
            f"targeting a {target_role} role.\n{resume_text}\n"
            f"Return JSON: {{\"extracted_skills\": [\"s1\", \"s2\"]}}"
        )
        raw_txt = gemini_text(prompt)
        res_data = parse_json_safe(raw_txt)
        if isinstance(res_data, dict):
            cv_skills = res_data.get("extracted_skills", [])

    # Pull JD skills for THIS role and experience level
    jd_skills, _ = get_jd_skills(target_role, years_of_experience)
    cv_lower = {s.lower() for s in cv_skills}
    missing_skills = [s for s in jd_skills if s.lower() not in cv_lower]

    prompt = f"""
    You are a rigorous technical interviewer for an experienced candidate
    switching into a {target_role} role with {years_of_experience} years of experience.

    Candidate existing skills: {cv_skills}
    Standard JD skills for this role and level: {jd_skills}
    Missing skills relative to the JD: {missing_skills}

    Generate the 10 most important interview questions you would ask this SWITCHER candidate.
    - Mix deep technical questions on their existing skills with scenario-based questions
      on how they'd ramp up on the missing skills.
    - Avoid trivia; prefer real-world problem, design, debugging, and trade-off questions.

    Return EXACTLY a pure JSON array of 10 strings.
    Example:
    [
      "Tell me about a system you designed end-to-end and how you handled scale.",
      "How would you quickly get productive in Kubernetes if your new team uses it heavily?",
      "..."
    ]
    """
    raw_questions = gemini_text(prompt)
    questions = parse_json_safe(raw_questions)
    if not isinstance(questions, list):
        questions = ["(Error generating questions. Please try again or re-upload your resume.)"]

    return jsonify({
        "status": "success",
        "mock_questions": questions[:10],
        "cv_skills": cv_skills,
        "missing_skills": missing_skills,
    })

# ── /api/fresher/submit-answers ────────────────────────────────────────────────
@app.route('/api/fresher/submit-answers', methods=['POST'])
def submit_fresher_answers():
    """
    Accepts: JSON
      - target_role (string)
      - submission (list of dicts: question, selected, correct, is_correct, skill)
      - score (int)
      - total (int)
      - cv_skills (list of strings)

    Returns: Re-evaluated skill ratings (1-5) based on actual test performance,
             and a gap comparison against a 0-YOE JD role.
    """
    data = request.json or {}
    target_role = data.get("target_role", "Unknown Role")
    submission = data.get("submission", [])
    score = data.get("score", 0)
    total = data.get("total", 0)
    cv_skills = data.get("cv_skills", [])

    # Tally correct vs total questions per skill
    skill_correct = {}
    skill_total = {}
    
    for item in submission:
        skill = item.get("skill", "Unknown")
        is_correct = item.get("is_correct", False)
        
        skill_total[skill] = skill_total.get(skill, 0) + 1
        if is_correct:
            skill_correct[skill] = skill_correct.get(skill, 0) + 1

    # Re-rate based on test accuracy
    actual_skill_ratings = {}
    for skill, t in skill_total.items():
        c = skill_correct.get(skill, 0)
        pct = c / t if t > 0 else 0
        
        if pct == 1.0: rating = 5
        elif pct >= 0.75: rating = 4
        elif pct >= 0.50: rating = 3
        elif pct > 0.0: rating = 2
        else: rating = 1
        
        actual_skill_ratings[skill] = rating

    # Compare JD skills (0 YOE) vs CV skills
    jd_skills, avg_compensation = get_jd_skills(target_role, "0")
    
    cv_lower = {s.lower() for s in cv_skills}
    matching_skills = []
    missing_skills = []
    
    for s in jd_skills:
        if s.lower() in cv_lower:
            matching_skills.append(s)
        else:
            missing_skills.append(s)

    # Gemini Roadmap & Readiness based on missing skills
    roadmap_info = get_roadmap_for_skills(missing_skills)
    
    prompt = f"""
    You are an expert career counselor.
    The candidate scored {score} out of {total} on their technical quiz.
    Their target role is {target_role}. 
    They are missing the following skills from a standard entry-level Job Description:
    {missing_skills}
    
    CRITICAL INSTRUCTION:
    Here is data extracted directly from our internal 'skills_learning_roadmap':
    {json.dumps(roadmap_info)}

    You MUST build your "fastest_way_to_learn" and "learning_roadmap" strictly using ONLY the courses, project names, and details provided in the internal roadmap data above! Do not invent or suggest generic courses outside of this provided context. Emphasize the specific project descriptions and course names mapped to their missing skills.

    Please synthesize this and provide:
    1. A "readiness_score" from 0 to 100.
    2. A "fastest_way_to_learn" summary string referencing specific courses and projects from the extracted roadmap data.
    3. A "learning_roadmap" which is an array of actionable step strings explicitly derived from the extracted roadmap data.
    
    Return pure JSON with keys: "readiness_score" (int), "fastest_way_to_learn" (string), "learning_roadmap" (list of strings).
    """
    
    gemini_advice = {}
    if missing_skills or roadmap_info:
        raw_resp = gemini_text(prompt)
        try:
            gemini_advice = parse_json_safe(raw_resp)
            if not isinstance(gemini_advice, dict) or not gemini_advice:
                raise ValueError("Empty or bad Gemini response")
        except Exception as e:
            print(f"Gemini advice parse failed: {e} — using rule-based fallback.")
            gemini_advice = _fallback_career_advice(missing_skills, cv_skills, score, total)
    else:
        gemini_advice = {
            "readiness_score": int( (score/total)*100 ) if total > 0 else 100,
            "fastest_way_to_learn": "You have all the required skills from the JD! Focus on advanced projects.",
            "learning_roadmap": ["Apply for jobs", "Contribute to open source", "Build complex portfolio projects"]
        }

    gap_analysis = {
        "jd_skills_required": jd_skills,
        "cv_skills_extracted": cv_skills,
        "matching_skills": matching_skills,
        "missing_skills": missing_skills,
        "matching_count": len(matching_skills),
        "missing_count": len(missing_skills),
        "avg_compensation": avg_compensation,
        "gemini_advice": gemini_advice
    }

    return jsonify({
        "status": "success",
        "message": "Answers evaluated successfully.",
        "score": score,
        "total": total,
        "skill_ratings": actual_skill_ratings,
        "gap_analysis": gap_analysis
    })

@app.route('/api/switcher/mock-voice', methods=['POST'])
def handle_switcher_mock_voice():
    """
    Mock Interview endpoint for Switchers.
    Pipeline:
      1. If audio uploaded -> Gemini Flash understands audio natively, transcribes user speech
         and generates the interviewer's next response as text.
      2. gTTS converts the text response to speech (MP3 -> base64).
      3. Returns both reply_text and reply_audio_b64 to frontend.
    """
    try:
        audio_file = request.files.get("audio")
        context_raw = request.form.get("context", "{}")
        context = json.loads(context_raw)

        target_role = context.get("target_role", "Software Engineer")
        cv_skills   = context.get("cv_skills", [])
        jd_skills   = context.get("jd_skills", [])
        history     = context.get("history", [])

        client = genai.Client(api_key=GEMINI_API_KEY)

        # Model used for "audio input -> interviewer text" generation.
        # You may not have access to all Gemini variants, so this is configurable.
        audio_text_models_raw = os.getenv("GEMINI_AUDIO_TEXT_MODELS", "").strip()
        if audio_text_models_raw:
            audio_text_models = [m.strip() for m in audio_text_models_raw.split(",") if m.strip()]
        else:
            audio_text_models = ["gemini-2.5-flash"]

        def extract_reply_text(resp_obj) -> str:
            """Best-effort extraction for SDK versions where resp.text may be empty."""
            try:
                t = getattr(resp_obj, "text", None)
                if isinstance(t, str) and t.strip():
                    return t.strip()
            except Exception:
                pass

            try:
                # Common structure: candidates[0].content.parts[*].text
                cands = getattr(resp_obj, "candidates", None) or []
                if not cands:
                    return ""
                parts = ((cands[0].content.parts if hasattr(cands[0], "content") else None) or [])
                texts = [getattr(p, "text", "") for p in parts if getattr(p, "text", "").strip()]
                joined = "\n".join(t for t in texts if t)
                return joined.strip()
            except Exception:
                return ""

        system_instruction = (
            f"You are a highly professional technical interviewer at a top tech company. "
            f"You are interviewing a candidate switching into the role of: {target_role}. "
            f"Candidate's existing skills from their CV: {cv_skills}. "
            f"Required skills for the role: {jd_skills}. "
            f"Rules: Ask ONE question at a time. Be encouraging but rigorous. "
            f"Evaluate both technical depth and how they would bridge skill gaps. "
            f"Keep responses concise (2-4 sentences max). "
            f"If this is the first message, greet them warmly and ask the first technical question."
        )

        # Read audio bytes (if any) and pass the correct MIME type to Gemini.
        audio_bytes = None
        audio_mime = "audio/wav"
        audio_present = bool(audio_file)
        if audio_file:
            audio_bytes = audio_file.read()
            if audio_bytes:
                audio_mime = getattr(audio_file, "mimetype", None) or audio_mime

        # Append conversation history as context text.
        history_text = ""
        for h in history:
            role_label = "Interviewer" if h.get("role") == "model" else "Candidate"
            history_text += f"\n{role_label}: {h.get('text', '')}"

        # Build the user message parts (text context + optional audio).
        parts_list = []
        if history_text:
            parts_list.append(types.Part.from_text(text=f"Conversation so far:{history_text}"))

        if audio_present and audio_bytes:
            parts_list.append(
                types.Part.from_text(
                    text=(
                        "The candidate just responded (audio follows). "
                        "Transcribe what they said, give brief feedback, then ask the next question."
                    )
                )
            )
            parts_list.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime))
        else:
            parts_list.append(
                types.Part.from_text(
                    text=(
                        "Start the interview now. "
                        "Greet the candidate and ask the first technical question relevant to their target role and skill gaps."
                    )
                )
            )

        contents = [types.Content(role="user", parts=parts_list)]

        # Gemini generates the interviewer's text response.
        # Some SDK versions/models reject `system_instruction` in config, so we fall back to the older format.
        last_err: Exception | None = None
        resp = None
        for model_name in audio_text_models:
            try:
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=0.7,
                            max_output_tokens=300,
                            system_instruction=system_instruction,
                        ),
                    )
                except Exception:
                    # Fallback: put the instruction inside the user prompt (previous behavior).
                    fallback_parts = [types.Part.from_text(text=system_instruction)]
                    if history_text:
                        fallback_parts.append(
                            types.Part.from_text(text=f"\nConversation so far:{history_text}")
                        )
                    if audio_present and audio_bytes:
                        fallback_parts.append(
                            types.Part.from_text(
                                text=(
                                    "\nThe candidate just responded (audio follows). "
                                    "Transcribe what they said, give brief feedback, then ask the next question."
                                )
                            )
                        )
                        fallback_parts.append(
                            types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime)
                        )
                    else:
                        fallback_parts.append(
                            types.Part.from_text(
                                text=(
                                    "\nStart the interview now. "
                                    "Greet the candidate and ask the first technical question relevant "
                                    "to their target role and skill gaps."
                                )
                            )
                        )

                    resp = client.models.generate_content(
                        model=model_name,
                        contents=[types.Content(role="user", parts=fallback_parts)],
                        config=types.GenerateContentConfig(
                            temperature=0.7,
                            max_output_tokens=300,
                        ),
                    )

                # If we got here without raising, break and use this resp
                break
            except Exception as e:
                last_err = e
                resp = None

        reply_text = extract_reply_text(resp) if resp is not None else ""
        if not reply_text:
            reply_text = "Thank you for your response. Let me ask you the next question."
        if last_err is not None and resp is None:
            # Bubble up for UI to show; but we still respond with a safe default below.
            print(f"[Mock Interview] audio->text model failed: {last_err}")

        # Convert the text reply to speech using Gemini 2.5 Flash TTS
        # (We return WAV bytes because Streamlit's `st.audio(..., format=...)` needs a known mime type.)
        audio_b64 = None
        audio_format = None
        try:
            import wave

            # Keep TTS input short to reduce timeouts/blank audio issues.
            tts_text = reply_text[:800].strip() or "Thank you."

            tts_resp = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=tts_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    # Default voice is okay, but a prebuilt voice keeps output consistent.
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name="Kore"
                            )
                        )
                    ),
                ),
            )

            pcm_data = (
                tts_resp.candidates[0]
                .content.parts[0]
                .inline_data.data
            )

            # SDK may return raw bytes or base64 string depending on version.
            pcm_bytes = (
                base64.b64decode(pcm_data) if isinstance(pcm_data, str) else pcm_data
            )

            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)   # 16-bit PCM
                wf.setframerate(24000)
                wf.writeframes(pcm_bytes)

            wav_buf.seek(0)
            audio_b64 = base64.b64encode(wav_buf.read()).decode("utf-8")
            audio_format = "wav"
        except Exception as tts_err:
            # Fallback to gTTS if Gemini TTS fails for any reason.
            print(f"Gemini TTS error (non-fatal): {tts_err}")
            try:
                from gtts import gTTS

                tts_text = reply_text[:800].strip() or "Thank you."
                tts = gTTS(text=tts_text, lang="en", tld="co.uk")
                audio_buffer = io.BytesIO()
                tts.write_to_fp(audio_buffer)
                audio_buffer.seek(0)
                audio_b64 = base64.b64encode(audio_buffer.read()).decode("utf-8")
                audio_format = "mp3"
            except Exception as gt_tts_err:
                print(f"gTTS error (non-fatal): {gt_tts_err}")
                audio_b64 = None
                audio_format = None

        print(
            f"[Mock Interview] Role: {target_role} | Audio input: {audio_present and bool(audio_bytes)} "
            f"| Reply: {reply_text[:80]}..."
        )

        return jsonify({
            "status": "success",
            "reply_text": reply_text,
            "reply_audio_b64": audio_b64,
            "audio_format": audio_format
        })

    except Exception as e:
        print(f"Switcher Voice Interview Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ── /ws/switcher/mock-voice (real-time streaming, Gemini Live API) ────────────
#
# Streamlit's `st.audio_input()` is not truly streaming (it uploads a full clip).
# This websocket endpoint forwards PCM chunks to Gemini Live (native audio output)
# and streams back audio chunks (as base64 WAV) + transcripts.
#
# Client protocol:
# - Client sends JSON text frame: {"type":"start","context":{...}}
# - Client sends binary frames: raw PCM16, little-endian, 16kHz mono
# - Client sends JSON: {"type":"turn_end"} to flush current user speech
# - Client sends JSON: {"type":"stop"} or closes socket
def _build_switcher_live_system_prompt(target_role: str, cv_skills: list, jd_skills: list) -> str:
    return (
        "You are a highly professional technical interviewer at a top tech company. "
        f"You are interviewing a candidate switching into the role of: {target_role}. "
        f"Candidate's existing skills from their CV: {cv_skills}. "
        f"Required skills for the role: {jd_skills}. "
        "Rules: Ask ONE question at a time. Be encouraging but rigorous. "
        "Evaluate both technical depth and how they would bridge skill gaps. "
        "Keep responses concise (2-4 sentences max). "
        "If this is the first user speech in the session, greet them warmly and ask the first technical question."
    )


def _pcm16_to_wav_bytes(pcm_bytes: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM bytes into a minimal WAV container."""
    import wave

    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    wav_buf.seek(0)
    return wav_buf.read()


def _to_bytes_maybe_base64(data) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        # Live API audio chunks are typically base64-encoded strings.
        return base64.b64decode(data)
    return b""


WS_HOST = os.getenv("VOICE_WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("VOICE_WS_PORT", "5001"))
WS_PATH = os.getenv("VOICE_WS_PATH", "/ws/switcher/mock-voice")
LIVE_NATIVE_AUDIO_MODEL = os.getenv(
    "GEMINI_LIVE_NATIVE_AUDIO_MODEL",
    "gemini-2.5-flash-native-audio-preview-12-2025",
)


async def _switcher_live_ws_handler(websocket, path: str):
    """Forward mic audio to Gemini Live and stream Gemini native audio back."""
    if path != WS_PATH:
        await websocket.close()
        return

    if not GEMINI_API_KEY:
        await websocket.send(json.dumps({"type": "error", "error": "Missing GEMINI_API_KEY"}))
        await websocket.close()
        return

    # Wait for start message
    start_raw = await websocket.recv()
    if not isinstance(start_raw, str):
        await websocket.send(json.dumps({"type": "error", "error": "Expected JSON start frame"}))
        await websocket.close()
        return

    start = json.loads(start_raw)
    if start.get("type") != "start":
        await websocket.send(json.dumps({"type": "error", "error": "Expected message type 'start'"}))
        await websocket.close()
        return

    context = start.get("context", {}) or {}
    target_role = context.get("target_role", "Software Engineer")
    cv_skills = context.get("cv_skills", []) or []
    jd_skills = context.get("jd_skills", []) or []
    history = context.get("history", []) or []

    system_prompt = _build_switcher_live_system_prompt(target_role, cv_skills, jd_skills)

    client = genai.Client(api_key=GEMINI_API_KEY)
    config = {
        "response_modalities": ["AUDIO"],
        # Include transcripts so the UI can display text alongside audio.
        "output_audio_transcription": {},
        "input_audio_transcription": {},
    }

    async with client.aio.live.connect(model=LIVE_NATIVE_AUDIO_MODEL, config=config) as session:
        # Provide interviewer instructions as a text turn.
        await session.send_client_content(
            turns=[{"role": "user", "parts": [{"text": system_prompt}]}],
            turn_complete=True,
        )

        if history:
            history_text = []
            for h in history[-6:]:
                role = "Interviewer" if h.get("role") == "model" else "Candidate"
                history_text.append(f"{role}: {h.get('text', '')}")
            ctx_summary = "Conversation so far (summary for continuity):\n" + "\n".join(history_text)
            await session.send_client_content(
                turns=[{"role": "user", "parts": [{"text": ctx_summary}]}],
                turn_complete=True,
            )

        async def send_audio_loop():
            async for msg in websocket:
                if isinstance(msg, str):
                    cmd = {}
                    try:
                        cmd = json.loads(msg)
                    except Exception:
                        cmd = {}
                    mtype = cmd.get("type")
                    if mtype == "turn_end":
                        await session.send_realtime_input(audio_stream_end=True)
                    elif mtype == "stop":
                        await session.send_realtime_input(audio_stream_end=True)
                        return
                else:
                    audio_chunk = msg
                    if audio_chunk:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=audio_chunk,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )

        async def receive_audio_loop():
            async for response in session.receive():
                if not response.server_content:
                    continue

                # Stream audio chunks back
                if response.server_content.model_turn and response.server_content.model_turn.parts:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            pcm_out = _to_bytes_maybe_base64(part.inline_data.data)
                            wav_bytes = _pcm16_to_wav_bytes(pcm_out, sample_rate=24000)
                            wav_b64 = base64.b64encode(wav_bytes).decode("utf-8")
                            await websocket.send(
                                json.dumps(
                                    {
                                        "type": "assistant_audio_chunk",
                                        "audio_wav_b64": wav_b64,
                                        "audio_format": "wav",
                                        "sample_rate": 24000,
                                    }
                                )
                            )

                # Forward transcripts (when enabled)
                if response.server_content.input_transcription:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "user_transcript",
                                "text": response.server_content.input_transcription.text,
                            }
                        )
                    )

                if response.server_content.output_transcription:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "assistant_transcript",
                                "text": response.server_content.output_transcription.text,
                            }
                        )
                    )

        send_task = asyncio.create_task(send_audio_loop())
        recv_task = asyncio.create_task(receive_audio_loop())

        done, pending = await asyncio.wait(
            {send_task, recv_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()


def _start_switcher_voice_ws_server():
    """
    Start websocket server in background so Flask can keep running.
    Requires: `pip install websockets`
    """
    # Flask debug reloader can re-import this module and start multiple websocket
    # servers. To avoid port-binding crashes, we only start if the port is free
    # and we safely handle "address already in use".
    def _is_port_open(host: str, port: int) -> bool:
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect((host, port))
                return True
        except Exception:
            return False

    if _is_port_open("127.0.0.1", WS_PORT) or os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        # Either already running, or Flask reloader isn't in the main worker.
        return

    try:
        import websockets  # type: ignore  # noqa: F401
    except Exception as e:
        print(
            "[WARNING] Real-time streaming websocket not started because "
            f"dependency is missing: websockets ({e})."
        )
        return

    async def _runner():
        import websockets
        try:
            async with websockets.serve(
                _switcher_live_ws_handler,
                WS_HOST,
                WS_PORT,
                ping_interval=20,
                ping_timeout=20,
                max_size=2**22,
            ):
                print(f"[WS] Listening on ws://{WS_HOST}:{WS_PORT}{WS_PATH}")
                await asyncio.Future()  # run forever
        except OSError as e:
            # Port already in use.
            print(f"[WARNING] WebSocket server not started: {e}")

    threading.Thread(target=lambda: asyncio.run(_runner()), daemon=True).start()


# ── /api/find-guide ────────────────────────────────────────────────────────────
GUIDE_POOL = [
    {
        "name": "Priya Sharma",
        "university": "IIT Delhi",
        "major": "Computer Science",
        "grad_year": 2019,
        "current_role": "Cloud Engineer",
        "company": "AWS",
        "years_exp": 5,
        "skills": ["AWS", "Kubernetes", "Terraform", "Python", "CI/CD"],
        "target_industry": "Cloud / DevOps",
        "bio": "I went from CS at IIT Delhi to a Cloud Engineer at AWS in 2 years. Happy to share my switching journey!",
    },
    {
        "name": "Marcus Lee",
        "university": "MIT",
        "major": "Computer Science",
        "grad_year": 2020,
        "current_role": "Machine Learning Engineer",
        "company": "Google DeepMind",
        "years_exp": 4,
        "skills": ["PyTorch", "TensorFlow", "Python", "MLOps", "Data Pipelines"],
        "target_industry": "AI / ML",
        "bio": "CS grad from MIT now building production ML systems at DeepMind. I mentor on bridging academics to real ML engineering.",
    },
    {
        "name": "Aisha Patel",
        "university": "NIT Trichy",
        "major": "Electronics Engineering",
        "grad_year": 2018,
        "current_role": "Full Stack Developer",
        "company": "Razorpay",
        "years_exp": 6,
        "skills": ["React", "Node.js", "PostgreSQL", "Docker", "TypeScript"],
        "target_industry": "Software Engineering",
        "bio": "ECE grad who self-taught full stack dev and landed at Razorpay. Proof you don't need a CS degree to make it!",
    },
    {
        "name": "Jordan Kim",
        "university": "Stanford University",
        "major": "Data Science",
        "grad_year": 2021,
        "current_role": "Data Scientist",
        "company": "Stripe",
        "years_exp": 3,
        "skills": ["Python", "SQL", "Spark", "dbt", "Looker", "Statistics"],
        "target_industry": "Data Science / Analytics",
        "bio": "I transitioned from academia to fintech data science at Stripe. Ask me about portfolio projects and SQL interviews!",
    },
    {
        "name": "Rahul Gupta",
        "university": "IIT Bombay",
        "major": "Computer Science",
        "grad_year": 2017,
        "current_role": "Software Engineer (SDE-III)",
        "company": "Meta",
        "years_exp": 7,
        "skills": ["C++", "Python", "System Design", "Distributed Systems", "React"],
        "target_industry": "Software Engineering",
        "bio": "IIT Bombay CS to Meta in 3 years. Cracked FAANG after 2 failed attempts. System design is my speciality.",
    },
    {
        "name": "Sophie Martin",
        "university": "University of Toronto",
        "major": "Information Systems",
        "grad_year": 2022,
        "current_role": "Product Manager",
        "company": "Shopify",
        "years_exp": 2,
        "skills": ["Product Roadmapping", "SQL", "UX Research", "Agile", "Analytics"],
        "target_industry": "Product Management",
        "bio": "From IS grad to PM at Shopify in under 2 years. I'll help you pivot from tech to product roles.",
    },
    {
        "name": "Chen Wei",
        "university": "Peking University",
        "major": "Mathematics",
        "grad_year": 2016,
        "current_role": "Quantitative Analyst",
        "company": "Goldman Sachs",
        "years_exp": 8,
        "skills": ["Python", "R", "Financial Modelling", "Statistics", "Machine Learning"],
        "target_industry": "Finance / Quant",
        "bio": "Math degree to Quant at Goldman. The transition is tough but I will guide you through the finance tech interview.",
    },
    {
        "name": "Fatima Al-Hassan",
        "university": "University of Edinburgh",
        "major": "Artificial Intelligence",
        "grad_year": 2020,
        "current_role": "AI Research Engineer",
        "company": "Hugging Face",
        "years_exp": 4,
        "skills": ["NLP", "Transformers", "PyTorch", "Python", "Research"],
        "target_industry": "AI / ML",
        "bio": "AI grad from Edinburgh now at Hugging Face. I specialize in NLP and open-source AI contributions.",
    },
]

def _match_guides_backend(university: str, major: str, grad_year: int, target_role: str) -> list:
    """Score and rank guides from GUIDE_POOL against user inputs."""
    scored = []
    uni_l    = university.lower().strip()
    major_l  = major.lower().strip()
    target_l = target_role.lower().strip()

    for g in GUIDE_POOL:
        score  = 0
        badges = []

        if uni_l and uni_l in g["university"].lower():
            score += 40
            badges.append("same_uni")

        major_words = set(major_l.split())
        g_major_words = set(g["major"].lower().split())
        if major_l and (major_words & g_major_words or major_l in g["major"].lower()):
            score += 30
            badges.append("same_major")

        if target_l and (target_l in g["target_industry"].lower() or
                         g["target_industry"].lower() in target_l):
            score += 20
            badges.append("same_industry")

        if grad_year and abs(g["grad_year"] - grad_year) <= 4:
            score += 10
            badges.append("similar_path")

        scored.append({**g, "match_score": score, "badges": badges})

    scored.sort(key=lambda x: (-len(x["badges"]), -x["match_score"]))
    return scored


@app.route('/api/find-guide', methods=['POST'])
def find_guide():
    """
    Accepts JSON: { university, major, grad_year, target_role }
    Returns: { guides: [...], gemini_tip: "..." }
    """
    data        = request.json or {}
    university  = data.get("university", "")
    major       = data.get("major", "")
    grad_year   = int(data.get("grad_year", 0) or 0)
    target_role = data.get("target_role", "")

    guides = _match_guides_backend(university, major, grad_year, target_role)

    # Ask Gemini for a personalised tip based on the best match
    gemini_tip = ""
    if guides:
        top = guides[0]
        if GEMINI_API_KEY:
            prompt = (
                f"A user studied {major} at {university} (class of {grad_year}) "
                f"and wants to become a {target_role}.\n"
                f"Their best guide match is {top['name']}, a {top['current_role']} at {top['company']} "
                f"who also studied {top['major']} at {top['university']}.\n\n"
                f"Write a single, warm, encouraging 2-sentence tip for the user on how to best "
                f"reach out to this guide and what to ask them first. Be specific and actionable."
            )
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                resp   = client.models.generate_content(
                    model="gemma-3-4b-it",
                    contents=prompt
                )
                gemini_tip = resp.text.strip()
            except Exception as e:
                print(f"Gemini tip error: {e} — using template fallback.")
                gemini_tip = _fallback_guide_tip(major, top["name"], top["current_role"])
        else:
            # ── Fallback tip when no API key ──
            gemini_tip = _fallback_guide_tip(major, top["name"], top["current_role"])

    return jsonify({
        "status": "success",
        "guides": guides,
        "gemini_tip": gemini_tip,
    })


# ══════════════════════════════════════════════════════════════════════════════
# ── Mentee CRUD Endpoints  (PostgreSQL-backed) ────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/mentees', methods=['GET'])
def list_mentees():
    """
    List all mentees with optional search & filter.

    Query params:
      q             — free-text search across name, target, skills
      category      — 'Fresher' or 'Switcher'
      min_progress  — integer 0-100, inclusive lower bound
      max_progress  — integer 0-100, inclusive upper bound
      sort          — one of: name_asc (default), name_desc,
                              progress_asc, progress_desc
    """
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort_by  = request.args.get("sort", "name_asc").strip()

    # ── Validate category filter ──
    if category and category not in VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid 'category' filter. Must be one of: "
                     f"{', '.join(VALID_CATEGORIES)}. Got: '{category}'."
        }), 400

    # ── Validate sort ──
    if sort_by not in VALID_SORT_OPTIONS:
        return jsonify({
            "error": f"Invalid 'sort' value. Must be one of: "
                     f"{', '.join(VALID_SORT_OPTIONS)}. Got: '{sort_by}'."
        }), 400

    # ── Validate progress range ──
    min_progress = request.args.get("min_progress")
    max_progress = request.args.get("max_progress")

    try:
        min_progress = int(min_progress) if min_progress is not None else None
    except ValueError:
        return jsonify({"error": "'min_progress' must be an integer between 0 and 100."}), 400

    try:
        max_progress = int(max_progress) if max_progress is not None else None
    except ValueError:
        return jsonify({"error": "'max_progress' must be an integer between 0 and 100."}), 400

    if min_progress is not None and not (0 <= min_progress <= 100):
        return jsonify({"error": "'min_progress' must be between 0 and 100."}), 400
    if max_progress is not None and not (0 <= max_progress <= 100):
        return jsonify({"error": "'max_progress' must be between 0 and 100."}), 400
    if min_progress is not None and max_progress is not None and min_progress > max_progress:
        return jsonify({
            "error": f"'min_progress' ({min_progress}) cannot be greater than "
                     f"'max_progress' ({max_progress})."
        }), 400

    try:
        results = db_list_mentees(
            q=q, category=category,
            min_progress=min_progress, max_progress=max_progress,
            sort_by=sort_by,
        )
        return jsonify({"status": "success", "count": len(results), "mentees": results})
    except Exception as e:
        print(f"[DB Error] list_mentees: {e}")
        return jsonify({"error": "Database error while fetching mentees. Please try again."}), 503


@app.route('/api/mentees/<mentee_id>', methods=['GET'])
def get_mentee(mentee_id: str):
    """View a single mentee by UUID."""
    # Basic UUID format check
    try:
        uuid.UUID(mentee_id)
    except ValueError:
        return jsonify({"error": f"'{mentee_id}' is not a valid mentee ID (expected UUID format)."}), 400

    try:
        mentee = db_get_mentee(mentee_id)
    except Exception as e:
        print(f"[DB Error] get_mentee: {e}")
        return jsonify({"error": "Database error while fetching mentee. Please try again."}), 503

    if not mentee:
        return jsonify({"error": f"Mentee with ID '{mentee_id}' was not found."}), 404
    return jsonify({"status": "success", "mentee": mentee})


@app.route('/api/mentees', methods=['POST'])
def create_mentee():
    """
    Create a new mentee.

    JSON body (Content-Type: application/json):
    {
        "name":     string  — required, 2-120 chars
        "target":   string  — required, 2-200 chars (target job role)
        "category": string  — required, "Fresher" or "Switcher"
        "progress": integer — optional, 0-100 (default 0)
        "skills":   array   — optional, max 50 strings
        "tasks":    array   — optional, max 30 objects {title: string, done: bool}
    }
    """
    if not request.is_json:
        return jsonify({
            "error": "Request must be JSON. Set 'Content-Type: application/json'."
        }), 415

    data = request.json or {}

    # ── Validate ──
    errors = _validate_mentee_payload(data, partial=False)
    if errors:
        return jsonify({
            "error": "Validation failed.",
            "details": errors
        }), 400

    name     = data["name"].strip()
    target   = data["target"].strip()
    category = data["category"]
    progress = max(0, min(100, int(data.get("progress", 0))))
    skills   = [s.strip() for s in data.get("skills", [])]
    tasks    = data.get("tasks", [])

    try:
        mentee = db_create_mentee(
            name=name, target=target, category=category,
            progress=progress, skills=skills, tasks=tasks,
        )
        return jsonify({"status": "created", "mentee": mentee}), 201
    except Exception as e:
        print(f"[DB Error] create_mentee: {e}")
        return jsonify({"error": "Database error while creating mentee. Please try again."}), 503


@app.route('/api/mentees/<mentee_id>', methods=['PUT'])
def update_mentee(mentee_id: str):
    """
    Partially update an existing mentee.

    Path param: mentee_id — UUID
    JSON body: any subset of { name, target, category, progress, skills, tasks }
    """
    # ── Validate ID format ──
    try:
        uuid.UUID(mentee_id)
    except ValueError:
        return jsonify({"error": f"'{mentee_id}' is not a valid mentee ID (expected UUID format)."}), 400

    if not request.is_json:
        return jsonify({
            "error": "Request must be JSON. Set 'Content-Type: application/json'."
        }), 415

    data = request.json or {}

    if not data:
        return jsonify({"error": "Request body is empty. Provide at least one field to update."}), 400

    # ── Validate provided fields only (partial=True) ──
    errors = _validate_mentee_payload(data, partial=True)
    if errors:
        return jsonify({
            "error": "Validation failed.",
            "details": errors
        }), 400

    # ── Normalise string fields ──
    updates: dict = {}
    if "name" in data:
        updates["name"] = data["name"].strip()
    if "target" in data:
        updates["target"] = data["target"].strip()
    if "category" in data:
        updates["category"] = data["category"]
    if "progress" in data:
        updates["progress"] = max(0, min(100, int(data["progress"])))
    if "skills" in data:
        updates["skills"] = [s.strip() for s in data["skills"]]
    if "tasks" in data:
        updates["tasks"] = data["tasks"]

    try:
        mentee = db_update_mentee(mentee_id, updates)
    except Exception as e:
        print(f"[DB Error] update_mentee: {e}")
        return jsonify({"error": "Database error while updating mentee. Please try again."}), 503

    if mentee is None:
        return jsonify({"error": f"Mentee with ID '{mentee_id}' was not found."}), 404

    return jsonify({"status": "updated", "mentee": mentee})


@app.route('/api/mentees/<mentee_id>', methods=['DELETE'])
def delete_mentee(mentee_id: str):
    """Permanently delete a mentee by UUID."""
    try:
        uuid.UUID(mentee_id)
    except ValueError:
        return jsonify({"error": f"'{mentee_id}' is not a valid mentee ID (expected UUID format)."}), 400

    try:
        deleted = db_delete_mentee(mentee_id)
    except Exception as e:
        print(f"[DB Error] delete_mentee: {e}")
        return jsonify({"error": "Database error while deleting mentee. Please try again."}), 503

    if not deleted:
        return jsonify({"error": f"Mentee with ID '{mentee_id}' was not found."}), 404

    return jsonify({"status": "deleted", "id": mentee_id})


if __name__ == '__main__':
    _start_switcher_voice_ws_server()
    app.run(debug=True, port=5000)
