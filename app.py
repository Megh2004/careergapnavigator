"""
Skill-Bridge Career Navigator
A personalized career gap analysis and learning roadmap platform.
Run with: streamlit run skill_bridge_app.py
"""
 
import os
import streamlit as st
import requests as http_requests
import base64
import json
import re
import time
import random
from datetime import datetime, timedelta
from fpdf import FPDF
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemma-3-27b-it")

def generate_detail_pdf(result, pct):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(10, 10, 10)
    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(190, 10, text="Skill-Bridge Career Details Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    
    gap = result.get("gap_analysis", {})
    if not gap:
        pdf.set_font("helvetica", size=12)
        pdf.cell(190, 10, text=f"Quiz Score: {pct}%", new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())
        
    pdf.set_font("helvetica", style="B", size=14)
    pdf.cell(190, 10, text=f"Test Score: {pct}%", new_x="LMARGIN", new_y="NEXT")
    
    avg_comp = gap.get("avg_compensation", "N/A")
    clean_comp = str(avg_comp).encode('latin-1', 'replace').decode('latin-1')
    pdf.cell(190, 10, text=f"Average Compensation for Role: {clean_comp}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    pdf.set_font("helvetica", style="B", size=12)
    pdf.cell(190, 8, text="Market Readiness (Vs. 0 YOE JD):", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=12)
    
    match_str = ", ".join(gap.get('matching_skills', []))
    miss_str = ", ".join(gap.get('missing_skills', []))
    
    # Safe rendering
    try:
        pdf.multi_cell(190, 8, text=f"Matched Skills: {match_str.encode('latin-1', 'replace').decode('latin-1')}")
        pdf.multi_cell(190, 8, text=f"Missing Skills: {miss_str.encode('latin-1', 'replace').decode('latin-1')}")
    except Exception:
        pdf.cell(190, 8, text="Matched Skills: [Text too long to map]", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(190, 8, text="Missing Skills: [Text too long to map]", new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)
    
    advice = gap.get("gemini_advice", {})
    if advice:
        pdf.set_font("helvetica", style="B", size=14)
        pdf.cell(190, 10, text=f"Readiness Score: {advice.get('readiness_score', 0)} / 100", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        
        pdf.set_font("helvetica", style="B", size=12)
        pdf.cell(190, 10, text="Learning Roadmap:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", size=11)
        for idx, step in enumerate(advice.get("learning_roadmap", [])):
            clean_step = str(step).encode('latin-1', 'replace').decode('latin-1')
            try:
                pdf.multi_cell(190, 8, text=f"{idx+1}. {clean_step}")
            except Exception:
                pass
                
        pdf.ln(5)
        
        pdf.set_font("helvetica", style="B", size=12)
        pdf.cell(190, 10, text="Fastest Way to Learn:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", size=11)
        fw = str(advice.get("fastest_way_to_learn", "")).encode('latin-1', 'replace').decode('latin-1')
        try:
            pdf.multi_cell(190, 8, text=fw)
        except Exception:
            pdf.cell(190, 8, text="See frontend for details.", new_x="LMARGIN", new_y="NEXT")
            
    return bytes(pdf.output())

# ── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Skill-Bridge | Career Navigator",
    page_icon="🌉",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Instrument+Sans:wght@400;500;600&display=swap');
 
/* ── Base Reset ── */
html, body, [class*="css"] {
    font-family: 'Instrument Sans', sans-serif;
}
 
/* ── Background ── */
.stApp {
    background: #0a0a0f;
    color: #e8e6e0;
}
 
/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0f0f1a !important;
    border-right: 1px solid #1e1e2e;
}
[data-testid="stSidebar"] * {
    color: #e8e6e0 !important;
}
 
/* ── Hero Header ── */
.hero-header::before {
    content: '';
    position: absolute;
    top: -60px; left: -60px;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 70%);
    pointer-events: none;
}
.hero-header::after {
    content: '';
    position: absolute;
    bottom: -40px; right: 60px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(245,158,11,0.08) 0%, transparent 70%);
    pointer-events: none;
}
.hero-title {
    font-family: 'Syne', sans-serif;
    font-size: 3rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    line-height: 1.1;
    background: linear-gradient(135deg, #ffffff 30%, #6366f1 70%, #f59e0b 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 0.5rem;
}
.hero-sub {
    font-size: 1.05rem;
    color: #6b6b8a;
    letter-spacing: 0.02em;
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
}
.hero-badge {
    display: inline-block;
    background: rgba(99,102,241,0.15);
    border: 1px solid rgba(99,102,241,0.3);
    color: #818cf8;
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    padding: 0.2rem 0.7rem;
    border-radius: 20px;
    letter-spacing: 0.08em;
    margin-bottom: 1rem;
    text-transform: uppercase;
}
 
/* ── Section Labels ── */
.section-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #6366f1;
    margin-bottom: 0.5rem;
}
 
/* ── Cards ── */
.card {
    background: #111118;
    border: 1px solid #1e1e2e;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.card:hover {
    border-color: #2e2e4e;
}
.card-title {
    font-family: 'Syne', sans-serif;
    font-size: 1rem;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 0.4rem;
}
.card-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #4b4b6b;
    margin-bottom: 0.8rem;
}
 
/* ── Skill Pills ── */
.pill-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.6rem 0; }
.pill {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    padding: 0.2rem 0.65rem;
    border-radius: 20px;
    font-weight: 500;
    letter-spacing: 0.03em;
}
.pill-green  { background: rgba(34,197,94,0.12); border: 1px solid rgba(34,197,94,0.25); color: #4ade80; }
.pill-red    { background: rgba(239,68,68,0.12);  border: 1px solid rgba(239,68,68,0.25);  color: #f87171; }
.pill-yellow { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.25); color: #fbbf24; }
.pill-indigo { background: rgba(99,102,241,0.12); border: 1px solid rgba(99,102,241,0.25); color: #818cf8; }
.pill-gray   { background: rgba(107,114,128,0.12);border: 1px solid rgba(107,114,128,0.25);color: #9ca3af; }
 
/* ── Metric Strip ── */
.metric-strip {
    display: flex;
    gap: 1rem;
    margin: 1.2rem 0;
}
.metric-box {
    flex: 1;
    background: #0f0f1a;
    border: 1px solid #1e1e2e;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    text-align: center;
}
.metric-num {
    font-family: 'Syne', sans-serif;
    font-size: 2rem;
    font-weight: 800;
    color: #ffffff;
    line-height: 1;
}
.metric-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: #4b4b6b;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 0.3rem;
}
 
/* ── Roadmap Timeline ── */
.timeline-item {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.2rem;
    align-items: flex-start;
}
.timeline-dot {
    width: 32px; height: 32px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Syne', sans-serif;
    font-size: 0.75rem;
    font-weight: 700;
    flex-shrink: 0;
    margin-top: 2px;
}
.dot-1 { background: rgba(99,102,241,0.2); border: 2px solid #6366f1; color: #818cf8; }
.dot-2 { background: rgba(245,158,11,0.2); border: 2px solid #f59e0b; color: #fbbf24; }
.dot-3 { background: rgba(34,197,94,0.2);  border: 2px solid #22c55e; color: #4ade80;  }
 
/* ── Interview Q cards ── */
.q-card {
    background: #0c0c16;
    border-left: 3px solid #6366f1;
    border-radius: 0 8px 8px 0;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
}
.q-text {
    font-size: 0.9rem;
    color: #d4d4f0;
    margin-bottom: 0.5rem;
    line-height: 1.5;
}
.q-hint {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #4b4b6b;
    border-top: 1px solid #1e1e2e;
    padding-top: 0.5rem;
    margin-top: 0.5rem;
}
 
/* ── Progress Bar ── */
.progress-bar-bg {
    background: #1e1e2e;
    border-radius: 4px;
    height: 6px;
    margin: 0.4rem 0 1rem;
    overflow: hidden;
}
.progress-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.8s ease;
}
 
/* ── Streamlit widget overrides ── */
.stTextArea textarea {
    background: #111118 !important;
    border: 1px solid #1e1e2e !important;
    color: #e8e6e0 !important;
    border-radius: 8px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.82rem !important;
}
.stTextInput input {
    background: #111118 !important;
    border: 1px solid #1e1e2e !important;
    color: #e8e6e0 !important;
    border-radius: 8px !important;
}
.stSelectbox > div > div {
    background: #111118 !important;
    border: 1px solid #1e1e2e !important;
    color: #e8e6e0 !important;
    border-radius: 8px !important;
}
.stButton > button {
    background: linear-gradient(135deg, #6366f1, #4f46e5) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: 0.03em !important;
    padding: 0.6rem 2rem !important;
    transition: opacity 0.2s !important;
}
.stButton > button:hover { opacity: 0.85 !important; }
 
div[data-testid="stTab"] button {
    font-family: 'Syne', sans-serif !important;
    font-weight: 600 !important;
    color: #6b6b8a !important;
}
div[data-testid="stTab"] button[aria-selected="true"] {
    color: #818cf8 !important;
    border-bottom-color: #6366f1 !important;
}

/* ── MCQ Test Cards ── */
.test-question-card {
    background: #111118;
    border: 1px solid #2e2e4e;
    border-radius: 14px;
    padding: 2rem 2.2rem;
    margin-bottom: 1.5rem;
}
.test-q-number {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #6366f1;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.6rem;
}
.test-q-text {
    font-family: 'Syne', sans-serif;
    font-size: 1.15rem;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.45;
    margin-bottom: 1.5rem;
}
.test-progress-bar {
    background: #1a1a2e;
    border-radius: 6px;
    height: 8px;
    margin-bottom: 0.4rem;
    overflow: hidden;
}
.test-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #6366f1, #818cf8);
    border-radius: 6px;
    transition: width 0.4s ease;
}
.option-hint {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #4b4b6b;
    margin-top: -0.8rem;
    margin-bottom: 1rem;
}
.skill-badge {
    display: inline-block;
    background: rgba(99,102,241,0.12);
    border: 1px solid rgba(99,102,241,0.25);
    color: #818cf8;
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    padding: 0.15rem 0.55rem;
    border-radius: 20px;
    margin-bottom: 1.2rem;
}
 
.stSpinner > div { border-top-color: #6366f1 !important; }
 
/* ── Divider ── */
hr { border-color: #1e1e2e !important; }
 
/* ── Warn / Info boxes ── */
.info-box {
    background: rgba(99,102,241,0.07);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 8px;
    padding: 0.8rem 1rem;
    font-size: 0.85rem;
    color: #a5b4fc;
    margin: 0.8rem 0;
}
.warn-box {
    background: rgba(245,158,11,0.07);
    border: 1px solid rgba(245,158,11,0.2);
    border-radius: 8px;
    padding: 0.8rem 1rem;
    font-size: 0.85rem;
    color: #fcd34d;
    margin: 0.8rem 0;
}
</style>
""", unsafe_allow_html=True)
 
 
# ── Gemini Client ────────────────────────────────────────────────────────────
@st.cache_resource
def get_gemini_client():
    if not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        return None


gemini_client = get_gemini_client()


# ── AI Helper (Gemini Text) ───────────────────────────────────────────────────
def call_gemini(prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    """Call Gemini for text generation. Returns '__NO_CLIENT__' or '__ERROR__'."""
    if not gemini_client:
        return "__NO_CLIENT__"
    try:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = gemini_client.models.generate_content(
            model=GEMINI_TEXT_MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.4,
            ),
        )
        return (resp.text or "").strip()
    except Exception as e:
        return f"__ERROR__: {e}"
 
 
def parse_json_from_response(text: str) -> dict | list | None:
    """Extract JSON from Claude response robustly."""
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
 
 
# ── Synthetic Fallback Data ────────────────────────────────────────────────────
FALLBACK_PROFILE = {
    "name": "Alex Rivera",
    "skills": ["Python", "SQL", "Data Analysis", "Pandas", "Matplotlib"],
    "experience_years": 2,
    "education": "B.Sc. Computer Science",
    "summary": "Junior data analyst with 2 years of experience in business intelligence."
}
 
FALLBACK_GAP = {
    "matched_skills": ["Python", "SQL", "Data Analysis"],
    "missing_critical": ["Apache Spark", "Kubernetes", "Terraform", "CI/CD Pipelines", "AWS/GCP"],
    "missing_nice": ["Scala", "Airflow", "dbt", "Kafka"],
    "transferable": ["Pandas → PySpark", "SQL → BigQuery", "Data Analysis → ML Pipelines"],
    "match_score": 42,
    "market_demand": {"Python": 95, "SQL": 90, "Spark": 88, "Kubernetes": 82, "Terraform": 78,
                      "CI/CD": 85, "AWS": 92, "Airflow": 70}
}
 
FALLBACK_ROADMAP = {
    "phase_1": {
        "label": "0–30 Days · Foundations",
        "items": [
            {"skill": "AWS Cloud Practitioner", "resource": "AWS Skill Builder (Free)", "hours": 20,
             "type": "Certification", "url": "https://aws.amazon.com/training/"},
            {"skill": "Docker & Containers", "resource": "Play with Docker (Free)", "hours": 10,
             "type": "Hands-on", "url": "https://labs.play-with-docker.com/"},
        ]
    },
    "phase_2": {
        "label": "30–60 Days · Core Skills",
        "items": [
            {"skill": "Apache Spark (PySpark)", "resource": "Databricks Academy (Free)", "hours": 25,
             "type": "Course", "url": "https://academy.databricks.com/"},
            {"skill": "Terraform Basics", "resource": "HashiCorp Learn (Free)", "hours": 15,
             "type": "Course", "url": "https://developer.hashicorp.com/terraform/tutorials"},
        ]
    },
    "phase_3": {
        "label": "60–90 Days · Specialization",
        "items": [
            {"skill": "Kubernetes (CKA prep)", "resource": "Killer.sh + KodeKloud", "hours": 30,
             "type": "Certification", "url": "https://kodekloud.com/"},
            {"skill": "Build a Data Pipeline Project", "resource": "Personal GitHub Project", "hours": 20,
             "type": "Project", "url": "https://github.com/"},
        ]
    }
}
 
FALLBACK_QUESTIONS = [
    {"question": "Explain the difference between Spark's RDD, DataFrame, and Dataset APIs.",
     "skill": "Apache Spark", "difficulty": "Mid",
     "hint": "Focus on type-safety, optimization via Catalyst, and when to use each."},
    {"question": "How would you design a CI/CD pipeline for a machine learning model?",
     "skill": "CI/CD Pipelines", "difficulty": "Senior",
     "hint": "Cover: source control, automated testing, model registry, deployment strategies (canary/blue-green)."},
    {"question": "What is Terraform state and why is remote state important?",
     "skill": "Terraform", "difficulty": "Mid",
     "hint": "Discuss state locking, S3 backend, and team collaboration risks with local state."},
    {"question": "Walk me through IAM roles vs policies in AWS.",
     "skill": "AWS", "difficulty": "Beginner",
     "hint": "Mention least privilege principle, inline vs managed policies, and role assumption."},
]
 
 
# ── Core Analysis Functions ────────────────────────────────────────────────────
def extract_profile(resume_text: str, github_url: str) -> dict:
    system = (
        "You are a precise resume parser. Extract structured data from the resume. "
        "Return ONLY valid JSON, no markdown, no preamble."
    )
    prompt = f"""Parse this resume and GitHub URL into structured JSON.
Resume:
{resume_text[:3000]}
 
GitHub URL: {github_url or 'Not provided'}
 
Return JSON with these exact keys:
{{
  "name": "string",
  "skills": ["list", "of", "technical", "skills"],
  "experience_years": number,
  "education": "string",
  "summary": "one sentence summary"
}}"""
    raw = call_gemini(prompt, system, max_tokens=800)
    if raw.startswith("__"):
        return FALLBACK_PROFILE
    result = parse_json_from_response(raw)
    return result if result else FALLBACK_PROFILE
 
 
def analyze_gap(profile: dict, target_role: str) -> dict:
    system = (
        "You are a senior technical recruiter and career coach with deep knowledge of hiring requirements. "
        "Return ONLY valid JSON, no markdown, no preamble."
    )
    user_skills = ", ".join(profile.get("skills", []))
    prompt = f"""Perform a gap analysis for this candidate targeting the role: "{target_role}".
 
Candidate skills: {user_skills}
Experience: {profile.get('experience_years', 0)} years
Education: {profile.get('education', '')}
 
Based on real-world job market data for "{target_role}", return JSON:
{{
  "matched_skills": ["skills the candidate already has that are required"],
  "missing_critical": ["top 5-6 critical missing skills for this role"],
  "missing_nice": ["3-4 nice-to-have missing skills"],
  "transferable": ["existing_skill → how it transfers to role skill"],
  "match_score": <integer 0-100 representing overall readiness>,
  "market_demand": {{"skill_name": <demand_score_0_to_100>, ...}}  
}}
 
market_demand should include all matched + missing_critical skills with realistic scores."""
    raw = call_gemini(prompt, system, max_tokens=1200)
    if raw.startswith("__"):
        return FALLBACK_GAP
    result = parse_json_from_response(raw)
    return result if result else FALLBACK_GAP
 
 
def generate_roadmap(gap: dict, target_role: str) -> dict:
    system = (
        "You are a learning path designer. Map skill gaps to the best free and paid resources. "
        "Return ONLY valid JSON, no markdown, no preamble."
    )
    missing = gap.get("missing_critical", []) + gap.get("missing_nice", [])
    prompt = f"""Create a 90-day learning roadmap for someone targeting "{target_role}".
 
Skills to learn: {', '.join(missing[:8])}
 
Return JSON with exactly this structure:
{{
  "phase_1": {{
    "label": "0–30 Days · Foundations",
    "items": [
      {{"skill": "skill name", "resource": "course/resource name", "hours": number,
        "type": "Course|Certification|Hands-on|Project", "url": "https://...", "free": true/false}}
    ]
  }},
  "phase_2": {{
    "label": "30–60 Days · Core Skills",
    "items": [...]
  }},
  "phase_3": {{
    "label": "60–90 Days · Specialization",
    "items": [...]
  }}
}}
 
Each phase should have 2-3 items. Include real, accurate URLs for well-known platforms."""
    raw = call_gemini(prompt, system, max_tokens=1500)
    if raw.startswith("__"):
        return FALLBACK_ROADMAP
    result = parse_json_from_response(raw)
    return result if result else FALLBACK_ROADMAP
 
 
def generate_interview_questions(gap: dict, target_role: str) -> list:
    system = (
        "You are a senior technical interviewer. Generate realistic, specific interview questions. "
        "Return ONLY valid JSON array, no markdown, no preamble."
    )
    skills = gap.get("missing_critical", [])[:5]
    prompt = f"""Generate 5 technical interview questions for a "{target_role}" role focusing on these skills: {', '.join(skills)}.
 
Return a JSON array:
[
  {{
    "question": "specific technical question",
    "skill": "which skill it tests",
    "difficulty": "Beginner|Mid|Senior",
    "hint": "key concepts the answer should cover"
  }}
]"""
    raw = call_gemini(prompt, system, max_tokens=1200)
    if raw.startswith("__"):
        return FALLBACK_QUESTIONS
    result = parse_json_from_response(raw)
    return result if isinstance(result, list) else FALLBACK_QUESTIONS
 
 
# ── Find Your Guide Mock Data & Matching ──────────────────────────────────────
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
        "bio": "IIT Bombay CS → Meta in 3 years. Cracked FAANG after 2 failed attempts. System design is my speciality.",
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
        "bio": "Math degree → Quant at Goldman. The transition is tough but I'll guide you through the finance tech interview.",
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

MATCH_SCORE_LABELS = {
    "same_uni": ("🎓 Same University", "#6366f1"),
    "same_major": ("📚 Same Major", "#f59e0b"),
    "similar_path": ("🔁 Similar Career Path", "#22c55e"),
    "same_industry": ("💼 Same Target Industry", "#06b6d4"),
}

def match_guides(user_uni: str, user_major: str, user_year: int, user_target: str) -> list:
    """Match guides from pool with a score. Returns sorted list with match badges."""
    scored = []
    uni_lower    = user_uni.lower().strip()
    major_lower  = user_major.lower().strip()
    target_lower = user_target.lower().strip()

    for g in GUIDE_POOL:
        score  = 0
        badges = []

        # Same university
        if uni_lower and uni_lower in g["university"].lower():
            score  += 40
            badges.append("same_uni")

        # Same / similar major (keyword overlap)
        major_words = set(major_lower.split())
        guide_major_words = set(g["major"].lower().split())
        if major_lower and (major_words & guide_major_words or major_lower in g["major"].lower()):
            score  += 30
            badges.append("same_major")

        # Same target industry
        if target_lower and (target_lower in g["target_industry"].lower() or g["target_industry"].lower() in target_lower):
            score  += 20
            badges.append("same_industry")

        # Similar graduation year (within 4 years)
        if user_year and abs(g["grad_year"] - user_year) <= 4:
            score  += 10
            badges.append("similar_path")

        scored.append({**g, "match_score": score, "badges": badges})

    # Sort: anything with >=1 badge first, then pure score
    scored.sort(key=lambda x: (-len(x["badges"]), -x["match_score"]))
    return scored


def render_find_guide(career_stage: str = "Fresher"):
    """Render the Find Your Guide feature inside an expander."""
    st.markdown("""
    <div style="background:linear-gradient(135deg,rgba(99,102,241,0.12),rgba(6,182,212,0.08));
                border:1px solid rgba(99,102,241,0.3); border-radius:14px;
                padding:1.5rem 1.8rem; margin-bottom:1.5rem">
        <div style="font-family:sans-serif;font-size:1.25rem;font-weight:800;color:#fff">
            &#x1F9ED; Find Your Guide
        </div>
        <div style="font-family:monospace;font-size:0.75rem;color:#6b6b8a;margin-top:0.3rem">
            Discover mentors who walked the exact same path as you
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        fg_uni   = st.text_input("Your University", placeholder="e.g. IIT Bombay, MIT, VIT ...", key="fg_uni")
        fg_major = st.text_input("Your Major / Field", placeholder="e.g. Computer Science, ECE ...", key="fg_major")
    with c2:
        fg_year   = st.number_input("Graduation Year (approx)", min_value=2000, max_value=2030,
                                     value=2023, step=1, key="fg_year")
        fg_target = st.text_input("Target Role / Industry", placeholder="e.g. Data Science, Cloud Engineer ...", key="fg_target")

    if st.button("🔍 Find Matching Guides", use_container_width=True, key="fg_search_btn"):
        with st.spinner("Matching guides based on your background..."):
            try:
                resp = http_requests.post(
                    "http://localhost:5000/api/find-guide",
                    json={
                        "university": fg_uni,
                        "major": fg_major,
                        "grad_year": int(fg_year),
                        "target_role": fg_target,
                    },
                    timeout=30,
                )
                if resp.ok:
                    data = resp.json()
                    st.session_state.guide_matches = data.get("guides", [])
                    st.session_state.guide_tip = data.get("gemini_tip", "")
                else:
                    st.session_state.guide_matches = match_guides(fg_uni, fg_major, int(fg_year), fg_target)
                    st.session_state.guide_tip = ""
            except Exception:
                st.session_state.guide_matches = match_guides(fg_uni, fg_major, int(fg_year), fg_target)
                st.session_state.guide_tip = ""

    matches = st.session_state.get("guide_matches", [])
    if not matches:
        return

    # Display the personalized tip from the backend (Gemini/Gemma)
    tip = st.session_state.get("guide_tip", "")
    if tip:
        st.markdown(
            '<div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.25);'
            'border-radius:12px;padding:1.1rem 1.4rem;margin-bottom:1.5rem;'
            'font-size:0.88rem;color:#a5b4fc;line-height:1.6; border-left:4px solid #6366f1">'
            '<span style="font-size:1.1rem;margin-right:8px">✨</span>'
            '<strong>AI networking Tip:</strong> ' + tip + "</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        '<p class="section-label" style="margin-top:0.5rem">Found '
        + str(len(matches)) + " Guides</p>",
        unsafe_allow_html=True,
    )

    import streamlit.components.v1 as components

    BADGE_META = {
        "same_uni":      ("#6366f1", "&#127891; Same University"),
        "same_major":    ("#f59e0b", "&#128218; Same Major"),
        "similar_path":  ("#22c55e", "&#128257; Similar Career Path"),
        "same_industry": ("#06b6d4", "&#128188; Same Target Industry"),
    }

    for g in matches:
        badges     = g.get("badges", [])
        ring       = BADGE_META[badges[0]][0] if badges else "#6366f1"
        score_pct  = min(g.get("match_score", 0), 100)
        score_col  = "#4ade80" if score_pct >= 60 else "#fbbf24" if score_pct >= 30 else "#9ca3af"
        initial    = g["name"][0]
        name       = g["name"]
        university = g["university"]
        major      = g["major"]
        grad_year  = str(g["grad_year"])
        role       = g["current_role"]
        company    = g["company"]
        years_exp  = str(g["years_exp"])
        bio        = g["bio"]

        # Build badge pills — pure concatenation, zero f-string quote nesting
        badge_parts = []
        for b in badges:
            bc, bl = BADGE_META[b]
            badge_parts.append(
                "<span style='background:rgba(0,0,0,0.35);border:1px solid "
                + bc + ";color:" + bc
                + ";font-family:monospace;font-size:0.65rem;"
                + "padding:0.18rem 0.6rem;border-radius:20px;margin-right:4px'>"
                + bl + "</span>"
            )
        badges_html = "".join(badge_parts) if badge_parts else (
            "<span style='color:#4b4b6b;font-size:0.7rem;font-family:monospace'>General Match</span>"
        )

        # Build skill pills
        skill_parts = [
            "<span style='background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.3);"
            "color:#818cf8;font-family:monospace;font-size:0.72rem;"
            "padding:0.2rem 0.65rem;border-radius:20px;margin-right:4px'>"
            + s + "</span>"
            for s in g["skills"][:4]
        ]
        skills_html = "".join(skill_parts)

        card = (
            "<div style='background:#111118;border:1px solid #1e1e2e;border-left:3px solid "
            + ring + ";border-radius:12px;padding:1.4rem 1.6rem;margin-bottom:1rem'>"

            # Header row
            + "<div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.8rem'>"
            +   "<div style='display:flex;align-items:center;gap:0.7rem'>"
            +     "<div style='width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,"
            +       ring + "40," + ring + "20);border:2px solid " + ring + ";display:flex;"
            +       "align-items:center;justify-content:center;font-weight:800;font-size:1.1rem;color:" + ring + "'>"
            +       initial
            +     "</div>"
            +     "<div>"
            +       "<div style='font-weight:700;color:#fff;font-size:1rem'>" + name + "</div>"
            +       "<div style='font-family:monospace;font-size:0.7rem;color:#6b6b8a'>"
            +         university + " &middot; " + major + " &middot; Class of " + grad_year
            +       "</div>"
            +     "</div>"
            +   "</div>"
            +   "<div style='text-align:right'>"
            +     "<div style='font-weight:800;color:" + score_col + ";font-size:1.6rem;line-height:1'>"
            +       str(score_pct) + "%"
            +     "</div>"
            +     "<div style='font-family:monospace;font-size:0.6rem;color:#4b4b6b;letter-spacing:0.1em'>MATCH</div>"
            +   "</div>"
            + "</div>"

            # Badges row
            + "<div style='margin-bottom:0.7rem'>" + badges_html + "</div>"

            # Info cards
            + "<div style='display:flex;gap:0.8rem;margin-bottom:0.8rem'>"
            +   "<div style='background:#0f0f1a;border:1px solid #1e1e2e;border-radius:8px;"
            +       "padding:0.6rem 0.9rem;flex:1'>"
            +     "<div style='font-family:monospace;font-size:0.58rem;color:#4b4b6b;"
            +         "text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.3rem'>Current Role</div>"
            +     "<div style='font-weight:700;color:#818cf8;font-size:0.85rem'>" + role + "</div>"
            +     "<div style='font-family:monospace;font-size:0.68rem;color:#6b6b8a'>@ "
            +       company + " &middot; " + years_exp + " yrs exp</div>"
            +   "</div>"
            +   "<div style='background:#0f0f1a;border:1px solid #1e1e2e;border-radius:8px;"
            +       "padding:0.6rem 0.9rem;flex:1'>"
            +     "<div style='font-family:monospace;font-size:0.58rem;color:#4b4b6b;"
            +         "text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.4rem'>Mentors On</div>"
            +     skills_html
            +   "</div>"
            + "</div>"

            # Bio
            + "<div style='background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);"
            +   "border-radius:8px;padding:0.75rem 1rem;font-size:0.82rem;color:#a5b4fc;"
            +   "line-height:1.6;font-style:italic'>"
            +   "&ldquo; " + bio + " &rdquo;"
            + "</div>"
            + "</div>"
        )
        components.html(card, height=260, scrolling=False)

    if st.button("✕ Close Guide Results", key="fg_close"):
        st.session_state.guide_matches = []
        st.session_state.guide_tip = ""
        st.rerun()


# ── UI Components ──────────────────────────────────────────────────────────────
def render_skill_pills(skills: list, cls: str):
    pills_html = "".join(f'<span class="pill {cls}">{s}</span>' for s in skills)
    st.markdown(f'<div class="pill-row">{pills_html}</div>', unsafe_allow_html=True)
 
 
def render_progress_bar(value: int, color: str = "#6366f1"):
    st.markdown(f"""
    <div class="progress-bar-bg">
        <div class="progress-bar-fill" style="width:{value}%; background:{color};"></div>
    </div>
    """, unsafe_allow_html=True)
 
 
def render_gap_dashboard(gap: dict, target_role: str):
    score = gap.get("match_score", 0)
    color = "#4ade80" if score >= 65 else "#fbbf24" if score >= 40 else "#f87171"
 
    # Metrics
    n_matched  = len(gap.get("matched_skills", []))
    n_missing  = len(gap.get("missing_critical", [])) + len(gap.get("missing_nice", []))
    n_transfer = len(gap.get("transferable", []))
 
    st.markdown(f"""
    <div class="metric-strip">
        <div class="metric-box">
            <div class="metric-num" style="color:{color}">{score}%</div>
            <div class="metric-label">Readiness Score</div>
        </div>
        <div class="metric-box">
            <div class="metric-num" style="color:#4ade80">{n_matched}</div>
            <div class="metric-label">Skills Matched</div>
        </div>
        <div class="metric-box">
            <div class="metric-num" style="color:#f87171">{n_missing}</div>
            <div class="metric-label">Gaps Found</div>
        </div>
        <div class="metric-box">
            <div class="metric-num" style="color:#fbbf24">{n_transfer}</div>
            <div class="metric-label">Transferable</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
 
    # Skill breakdown
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<p class="section-label">✅ You Already Have</p>', unsafe_allow_html=True)
        render_skill_pills(gap.get("matched_skills", []), "pill-green")
 
        st.markdown('<p class="section-label" style="margin-top:1rem">🔁 Transferable Skills</p>', unsafe_allow_html=True)
        for t in gap.get("transferable", []):
            st.markdown(f'<span class="pill pill-yellow">{t}</span> ', unsafe_allow_html=True)
 
    with col2:
        st.markdown('<p class="section-label">🚨 Critical Gaps</p>', unsafe_allow_html=True)
        render_skill_pills(gap.get("missing_critical", []), "pill-red")
 
        st.markdown('<p class="section-label" style="margin-top:1rem">💡 Nice to Have</p>', unsafe_allow_html=True)
        render_skill_pills(gap.get("missing_nice", []), "pill-indigo")
 
    # Market demand bars
    st.markdown("---")
    st.markdown('<p class="section-label">📊 Market Demand by Skill</p>', unsafe_allow_html=True)
    demand = gap.get("market_demand", {})
    for skill, val in sorted(demand.items(), key=lambda x: -x[1])[:8]:
        col_a, col_b = st.columns([3, 1])
        with col_a:
            bar_color = "#4ade80" if skill in gap.get("matched_skills", []) else "#6366f1"
            st.markdown(f'<span style="font-family:\'DM Mono\',monospace;font-size:0.78rem;color:#9ca3af">{skill}</span>', unsafe_allow_html=True)
            render_progress_bar(val, bar_color)
        with col_b:
            st.markdown(f'<p style="font-family:\'Syne\',sans-serif;font-weight:700;color:#ffffff;margin-top:0.3rem;text-align:right">{val}%</p>', unsafe_allow_html=True)
 
 
def render_roadmap(roadmap: dict):
    dot_classes = ["dot-1", "dot-2", "dot-3"]
    phase_colors = ["#6366f1", "#f59e0b", "#22c55e"]
    type_icons = {"Course": "📚", "Certification": "🏆", "Hands-on": "🛠️", "Project": "🚀"}
    total_hours = 0
 
    for i, (phase_key, dot_cls, ph_color) in enumerate(
            zip(["phase_1", "phase_2", "phase_3"], dot_classes, phase_colors)):
        phase = roadmap.get(phase_key, {})
        if not phase:
            continue
 
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem">
            <div class="timeline-dot {dot_cls}">{i+1}</div>
            <span style="font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;color:#ffffff">
                {phase.get('label', f'Phase {i+1}')}
            </span>
        </div>""", unsafe_allow_html=True)
 
        for item in phase.get("items", []):
            hours = item.get("hours", 0)
            total_hours += hours
            free_tag = '<span class="pill pill-green" style="font-size:0.65rem;padding:0.1rem 0.5rem">FREE</span>' if item.get("free", True) else '<span class="pill pill-indigo" style="font-size:0.65rem;padding:0.1rem 0.5rem">PAID</span>'
            icon = type_icons.get(item.get("type", "Course"), "📖")
            url = item.get("url", "#")
 
            st.markdown(f"""
            <div class="card" style="border-left:3px solid {ph_color};margin-left:2.5rem">
                <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                        <div class="card-title">{icon} {item.get('skill','')}</div>
                        <div class="card-meta">{item.get('resource','')} &nbsp;·&nbsp; {hours}h estimated</div>
                    </div>
                    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.4rem">
                        {free_tag}
                        <span class="pill pill-gray" style="font-size:0.65rem;padding:0.1rem 0.5rem">{item.get('type','')}</span>
                    </div>
                </div>
                <a href="{url}" target="_blank" style="font-family:'DM Mono',monospace;font-size:0.72rem;color:#6366f1;text-decoration:none">
                    → {url}
                </a>
            </div>""", unsafe_allow_html=True)
 
        st.markdown("<div style='margin-bottom:1.5rem'></div>", unsafe_allow_html=True)
 
    st.markdown(f"""
    <div class="info-box">
        ⏱️ <strong>Total estimated time:</strong> ~{total_hours} hours &nbsp;·&nbsp;
        At 1hr/day this roadmap completes in ~{total_hours} days
    </div>""", unsafe_allow_html=True)
 
 
def render_interview_prep(questions: list):
    diff_colors = {"Beginner": "#4ade80", "Mid": "#fbbf24", "Senior": "#f87171"}
 
    for i, q in enumerate(questions, 1):
        diff = q.get("difficulty", "Mid")
        color = diff_colors.get(diff, "#9ca3af")
        st.markdown(f"""
        <div class="q-card">
            <div style="display:flex;justify-content:space-between;margin-bottom:0.5rem">
                <span style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#6366f1">
                    Q{i} · {q.get('skill','')}
                </span>
                <span class="pill" style="background:rgba(0,0,0,0.2);border:1px solid {color}33;
                    color:{color};font-size:0.65rem;padding:0.1rem 0.5rem">
                    {diff}
                </span>
            </div>
            <div class="q-text">{q.get('question','')}</div>
            <div class="q-hint">💡 Key concepts: {q.get('hint','')}</div>
        </div>""", unsafe_allow_html=True)
 
 
# ── Main Content ───────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero-header">
    <div class="hero-badge">Career Intelligence · Skill-Bridge</div>
    <div class="hero-title">Bridge the Gap.<br>Build Your Career.</div>
    <div class="hero-sub">get personalized guidance for your career</div>
</div>
""", unsafe_allow_html=True)
 
# ── State Init ─────────────────────────────────────────────────────────────────
if "analysis_done" not in st.session_state:
    st.session_state.analysis_done = False
if "profile" not in st.session_state:
    st.session_state.profile = None
if "gap" not in st.session_state:
    st.session_state.gap = None
if "roadmap" not in st.session_state:
    st.session_state.roadmap = None
if "questions" not in st.session_state:
    st.session_state.questions = None
if "target_role" not in st.session_state:
    st.session_state.target_role = ""
if "career_stage" not in st.session_state:
    st.session_state.career_stage = "Fresher"
if "backend_response" not in st.session_state:
    st.session_state.backend_response = None
# ── Fresher test flow state
if "test_active" not in st.session_state:
    st.session_state.test_active = False
if "test_q_index" not in st.session_state:
    st.session_state.test_q_index = 0
if "test_answers" not in st.session_state:
    st.session_state.test_answers = {}
if "test_submitted" not in st.session_state:
    st.session_state.test_submitted = False
if "test_result" not in st.session_state:
    st.session_state.test_result = None
if "fresher_action" not in st.session_state:
    st.session_state.fresher_action = "gap"
if "mock_active" not in st.session_state:
    st.session_state.mock_active = False
if "show_find_guide" not in st.session_state:
    st.session_state.show_find_guide = False
if "guide_matches" not in st.session_state:
    st.session_state.guide_matches = []
if "show_add_mentee" not in st.session_state:
    st.session_state.show_add_mentee = False

# Define form variables with defaults
resume_text = ""
github_url = ""
target_role = ""
analyze_btn = False

if not st.session_state.analysis_done:
    st.markdown('<p class="section-label">User Type</p>', unsafe_allow_html=True)
    
    career_stage = st.radio(
        "Career Stage", 
        ["Fresher", "Switcher", "Mentor"], 
        horizontal=True,
        label_visibility="collapsed"
    )
    
    stage_years_exp = ""
    mentee_category = ""
    mentee_years_exp = ""

    if career_stage == "Switcher":
        stage_years_exp = st.text_input("Years of Experience", placeholder="e.g. 3")
    elif career_stage == "Mentor":
        mentee_category = st.selectbox("Category of Mentee", ["Fresher", "Switcher"])
        if mentee_category == "Switcher":
            mentee_years_exp = st.text_input("Mentee's Years of Experience", placeholder="e.g. 2")

    if career_stage != "Mentor":
        st.markdown("---")
        st.markdown('<p class="section-label">Target Role</p>', unsafe_allow_html=True)

        target_role_sel = st.selectbox(
            "Select Role",
            ["Software Engineer (SDE)", "Machine Learning / AI Engineer", "Full Stack Developer", "Data Scientist", "Cloud Engineer", "Others"],
            label_visibility="collapsed"
        )

        if target_role_sel == "Others":
            custom_role = st.text_input("Please specify your custom role", placeholder="e.g. Blockchain Developer")
            target_role = custom_role.strip() if custom_role.strip() else target_role_sel
        else:
            target_role = target_role_sel

        st.markdown("---")
        st.markdown('<p class="section-label">Your Profile</p>', unsafe_allow_html=True)

        resume_text = st.text_area(
            "Paste Resume / Skills",
            height=180,
            placeholder="Paste your resume text, skills list, or work experience here...\n\nExample:\n• Python, SQL, Pandas\n• 2 years data analysis\n• B.Sc. Computer Science\n• Built ETL pipelines at startup",
            label_visibility="collapsed"
        )

        github_url = st.text_input(
            "GitHub / Portfolio URL",
            placeholder="https://github.com/yourusername",
            label_visibility="collapsed"
        )
        st.markdown('<p style="font-family:\'DM Mono\',monospace;font-size:0.65rem;color:#4b4b6b;margin-top:-0.5rem">optional · enhances analysis</p>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<p class="section-label">Upload CV Document</p>', unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader("Upload your CV (PDF)", type=["pdf"], label_visibility="collapsed")
        if uploaded_file is not None:
            try:
                pdf_bytes = uploaded_file.getvalue()
                st.session_state.uploaded_pdf_bytes = pdf_bytes
                if "parsed_pdf_id" not in st.session_state or st.session_state.parsed_pdf_id != uploaded_file.file_id:
                    st.success("✅ PDF attached successfully! Click Analyze to build your path.")
                    st.session_state.parsed_pdf_id = uploaded_file.file_id
            except Exception as e:
                st.error(f"Error reading PDF file: {e}")

    else:
        st.markdown(
            '<div class="info-box">Mentor mode keeps things simple: manage mentees and track progress below.</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    
    btn_gap = False; btn_roadmap = False; btn_mock = False

    if career_stage == "Fresher":
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("<div style='text-align:center; font-size:1.8rem; margin-bottom:0.4rem'>🔬</div>", unsafe_allow_html=True)
            btn_gap = st.button("Gap Analysis", use_container_width=True)
            st.markdown("<div style='text-align:center; font-size:0.82rem; color:#6b6b8a; line-height:1.5; padding-top:0.4rem;'>Compares your skills against 100+ real job postings and highlights what's missing.</div>", unsafe_allow_html=True)

        with col2:
            st.markdown("<div style='text-align:center; font-size:1.8rem; margin-bottom:0.4rem'>🎤</div>", unsafe_allow_html=True)
            btn_mock = st.button("Mock Interview", use_container_width=True)
            st.markdown("<div style='text-align:center; font-size:0.82rem; color:#6b6b8a; line-height:1.5; padding-top:0.4rem;'>Technical questions generated specifically for your skill gaps — not generic prep.</div>", unsafe_allow_html=True)

        with col3:
            st.markdown("<div style='text-align:center; font-size:1.8rem; margin-bottom:0.4rem'>🧭</div>", unsafe_allow_html=True)
            btn_guide_fresher = st.button("Find Your Guide", use_container_width=True, key="fresher_guide_btn")
            st.markdown("<div style='text-align:center; font-size:0.82rem; color:#6b6b8a; line-height:1.5; padding-top:0.4rem;'>Connect with mentors who went to the same university or followed a similar path.</div>", unsafe_allow_html=True)
        
        # Gap analysis serves as the main analyzer entrypoint for freshers
        if btn_gap:
            st.session_state.fresher_action = "gap"
            st.session_state.show_find_guide = False
            analyze_btn = True
        if btn_mock:
            st.session_state.fresher_action = "mock"
            st.session_state.show_find_guide = False
            analyze_btn = True
        if btn_guide_fresher:
            st.session_state.show_find_guide = True
            st.session_state.guide_matches = []
    elif career_stage == "Switcher":
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("<div style='text-align:center; font-size:1.8rem; margin-bottom:0.4rem'>🔬</div>", unsafe_allow_html=True)
            btn_gap = st.button("Gap Analysis", use_container_width=True)
            st.markdown("<div style='text-align:center; font-size:0.82rem; color:#6b6b8a; line-height:1.5; padding-top:0.4rem;'>Compares your skills against 100+ real job postings and highlights what's missing.</div>", unsafe_allow_html=True)
        with col2:
            st.markdown("<div style='text-align:center; font-size:1.8rem; margin-bottom:0.4rem'>🎤</div>", unsafe_allow_html=True)
            btn_mock = st.button("Mock Interview", use_container_width=True)
            st.markdown("<div style='text-align:center; font-size:0.82rem; color:#6b6b8a; line-height:1.5; padding-top:0.4rem;'>Technical questions generated specifically for your skill gaps — not generic prep.</div>", unsafe_allow_html=True)
        with col3:
            st.markdown("<div style='text-align:center; font-size:1.8rem; margin-bottom:0.4rem'>🧭</div>", unsafe_allow_html=True)
            btn_guide_switcher = st.button("Find Your Guide", use_container_width=True, key="switcher_guide_btn")
            st.markdown("<div style='text-align:center; font-size:0.82rem; color:#6b6b8a; line-height:1.5; padding-top:0.4rem;'>Connect with mentors who made the same career switch you are planning.</div>", unsafe_allow_html=True)
        
        # In Switcher mode, Gap Analysis also triggers the full processing
        if btn_gap:
            st.session_state.switcher_view = "gap"
            st.session_state.show_find_guide = False
            analyze_btn = True
        if btn_mock:
            st.session_state.switcher_view = "mock"
            st.session_state.show_find_guide = False
            analyze_btn = True
        if btn_guide_switcher:
            st.session_state.show_find_guide = True
            st.session_state.guide_matches = []
    elif career_stage == "Mentor":
        st.markdown("---")
        st.markdown('<p class="section-label">Mentor Dashboard</p>', unsafe_allow_html=True)
        
        # ── Action buttons row ──
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button(" View My Mentees Progress", use_container_width=True):
                st.session_state.show_mentee_progress = True
                st.session_state.show_add_mentee = False
        with btn_col2:
            if st.button(" Add New Mentee", use_container_width=True):
                st.session_state.show_add_mentee = True
                st.session_state.show_mentee_progress = False

        # ── Add Mentee Form (Create) ──────────────────────────────────────────
        if st.session_state.get("show_add_mentee"):
            st.markdown("###  Add a New Mentee")
            with st.form("add_mentee_form"):
                new_name     = st.text_input("Mentee Name", placeholder="e.g. Alex Johnson")
                new_target   = st.text_input("Target Role", placeholder="e.g. Data Scientist")
                new_category = st.selectbox("Category", ["Fresher", "Switcher"])
                new_progress = st.slider("Current Progress (%)", 0, 100, 0)
                new_skills   = st.text_input("Skills (comma-separated)", placeholder="e.g. Python, SQL, Pandas")
                submitted    = st.form_submit_button(" Save Mentee", use_container_width=True)

                if submitted and new_name.strip() and new_target.strip():
                    payload = {
                        "name": new_name.strip(),
                        "target": new_target.strip(),
                        "category": new_category,
                        "progress": new_progress,
                        "skills": [s.strip() for s in new_skills.split(",") if s.strip()],
                        "tasks": [],
                    }
                    try:
                        resp = http_requests.post("http://localhost:5000/api/mentees", json=payload, timeout=10)
                        if resp.ok:
                            st.success(f" Mentee **{new_name}** created successfully!")
                            st.session_state.show_add_mentee = False
                            st.session_state.show_mentee_progress = True
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(resp.json().get("error", "Failed to create mentee."))
                    except Exception as e:
                        st.error(f"Backend unreachable: {e}")

            if st.button("✕ Cancel", key="cancel_add_mentee"):
                st.session_state.show_add_mentee = False
                st.rerun()

        # ── Mentee Progress View (Read / Update / Delete + Search/Filter) ─────
        if st.session_state.get("show_mentee_progress"):
            st.markdown("###  Your Assigned Mentees")

            # ── Filters ──
            fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1])
            with fc1:
                filter_q = st.text_input(" Search", placeholder="Name, role, or skill...", key="mentee_search_q")
            with fc2:
                filter_cat = st.selectbox("Category", ["All", "Fresher", "Switcher"], key="mentee_filter_cat")
            with fc3:
                filter_min = st.number_input("Min Progress", 0, 100, 0, key="mentee_min_prog")
            with fc4:
                filter_max = st.number_input("Max Progress", 0, 100, 100, key="mentee_max_prog")
            
            sort_option = st.selectbox("Sort by", ["Name (A-Z)", "Name (Z-A)", "Progress ↑", "Progress ↓"], key="mentee_sort")
            sort_map = {"Name (A-Z)": "name_asc", "Name (Z-A)": "name_desc", "Progress ↑": "progress_asc", "Progress ↓": "progress_desc"}

            # ── Fetch from backend ──
            params = {"sort": sort_map.get(sort_option, "name_asc")}
            if filter_q.strip():
                params["q"] = filter_q.strip()
            if filter_cat != "All":
                params["category"] = filter_cat
            if filter_min > 0:
                params["min_progress"] = filter_min
            if filter_max < 100:
                params["max_progress"] = filter_max

            mentees = []
            try:
                resp = http_requests.get("http://localhost:5000/api/mentees", params=params, timeout=10)
                if resp.ok:
                    mentees = resp.json().get("mentees", [])
            except Exception:
                st.warning("⚠️ Could not reach backend. Showing cached data.")

            if not mentees:
                st.info("No mentees match your filters. Try broadening your search.")
            
            for m in mentees:
                m_id = m.get("id", "")
                cat_badge = "🟢 Fresher" if m.get("category") == "Fresher" else "🔁 Switcher"
                with st.expander(f"👤 {m['name']} — {m['target']} ({m.get('progress', 0)}%)  [{cat_badge}]"):
                    col_m1, col_m2 = st.columns([1, 1])
                    with col_m1:
                        st.markdown("**Core Skills Learning:**")
                        for s in m.get("skills", []):
                            st.markdown(f"- {s}")
                    with col_m2:
                        st.markdown("**Tasks:**")
                        tasks = m.get("tasks", [])
                        for t in tasks:
                            if isinstance(t, dict):
                                icon = "✅" if t.get("done") else "□"
                                st.markdown(f"{icon} {t.get('title', '')}")
                            else:
                                st.markdown(f"□ {t}")
                    
                    st.progress(m.get("progress", 0) / 100)

                    # ── Inline Update ──
                    st.markdown("---")
                    new_prog = st.slider(f"Update progress for {m['name']}", 0, 100, m.get("progress", 0), key=f"prog_{m_id}")
                    uc1, uc2 = st.columns(2)
                    with uc1:
                        if st.button(f"💾 Save Progress", key=f"save_{m_id}", use_container_width=True):
                            try:
                                resp = http_requests.put(
                                    f"http://localhost:5000/api/mentees/{m_id}",
                                    json={"progress": new_prog}, timeout=10
                                )
                                if resp.ok:
                                    st.success(f"✅ {m['name']} progress updated to {new_prog}%")
                                    time.sleep(0.5)
                                    st.rerun()
                            except Exception:
                                st.error("Failed to update.")
                    with uc2:
                        if st.button(f"🗑️ Remove Mentee", key=f"del_{m_id}", use_container_width=True):
                            try:
                                resp = http_requests.delete(
                                    f"http://localhost:5000/api/mentees/{m_id}", timeout=10
                                )
                                if resp.ok:
                                    st.success(f"✅ {m['name']} removed.")
                                    time.sleep(0.5)
                                    st.rerun()
                            except Exception:
                                st.error("Failed to delete.")

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Close Progress View"):
                st.session_state.show_mentee_progress = False
                st.rerun()
            
    # ── Find Your Guide inline rendering ──────────────────────────────────────
    if st.session_state.get("show_find_guide") and career_stage in ["Fresher", "Switcher"]:
        st.markdown("---")
        render_find_guide(career_stage)
        st.stop()

# ── On Analyze ─────────────────────────────────────────────────────────────────
if analyze_btn:
    # Validation
    valid = True
    if not (resume_text.strip() or st.session_state.get("uploaded_pdf_bytes")):
        st.markdown("""<div class="warn-box">⚠️ Please paste your resume or upload a CV document to begin analysis.</div>""", unsafe_allow_html=True)
        valid = False
    elif career_stage == "Switcher" and not stage_years_exp.strip():
        st.markdown("""<div class="warn-box">⚠️ Please enter your current Years of Experience before starting Gap Analysis.</div>""", unsafe_allow_html=True)
        valid = False
        
    if valid:
        st.session_state.target_role = target_role
        st.session_state.career_stage = career_stage

        with st.spinner(""):
            progress_placeholder = st.empty()
            steps = [
                ("🔍 Parsing your profile...", 0.25),
                ("📊 Running gap analysis against market data...", 0.55),
                ("🗺️ Generating your learning roadmap...", 0.80),
                ("❓ Preparing mock interview questions...", 0.95),
            ]
            progress_bar = progress_placeholder.progress(0, text="Starting analysis…")

            # ── Build multipart payload for Flask backend ───────────────────
            # Get PDF bytes from the uploaded file (stored in session state)
            pdf_bytes = None
            if st.session_state.get("gemini_parsed_text"):
                # Re-read the PDF bytes from the uploader if available
                pass  # pdf_bytes set below

            # Retrieve raw PDF bytes stored during upload
            pdf_bytes = st.session_state.get("uploaded_pdf_bytes")

            form_data = {
                "target_role": target_role,
                "github_url": github_url,
                "resume_text": resume_text,
            }
            if career_stage == "Switcher":
                form_data["years_of_experience"] = stage_years_exp
            elif career_stage == "Mentor":
                form_data["mentee_category"] = mentee_category
                if mentee_category == "Switcher":
                    form_data["mentee_years_experience"] = mentee_years_exp

            # ── POST to correct Flask endpoint (multipart) ──────────────────
            BACKEND_URL = "http://localhost:5000"
            endpoint_map = {
                "Fresher": f"{BACKEND_URL}/api/career-stage/fresher",
                "Switcher": f"{BACKEND_URL}/api/career-stage/switcher",
                "Mentor":  f"{BACKEND_URL}/api/career-stage/mentor",
            }
            if career_stage == "Fresher" and st.session_state.get("fresher_action") == "mock":
                endpoint_map["Fresher"] = f"{BACKEND_URL}/api/career-stage/fresher/mock"
            if career_stage == "Switcher" and st.session_state.get("switcher_view") == "mock":
                endpoint_map["Switcher"] = f"{BACKEND_URL}/api/career-stage/switcher/mock"
            try:
                files = {}
                if pdf_bytes:
                    files = {"pdf": ("resume.pdf", pdf_bytes, "application/pdf")}

                if files:
                    resp = http_requests.post(
                        endpoint_map[career_stage],
                        data=form_data,
                        files=files,
                        timeout=60
                    )
                else:
                    # No PDF uploaded — notify but don't block the AI pipeline
                    resp = None
                    st.session_state.backend_response = {
                        "warning": "No PDF uploaded. Upload a CV PDF for skill rating and MCQ generation."
                    }

                if resp is not None:
                    if resp.ok:
                        st.session_state.backend_response = resp.json()
                    else:
                        st.session_state.backend_response = {"error": resp.text}
            except http_requests.exceptions.ConnectionError:
                st.session_state.backend_response = {
                    "error": "Flask backend not reachable. Run main.py to start both services."
                }


            # ── AI analysis pipeline ───────────────────────────────────────
            progress_bar.progress(0.05, text=steps[0][0])
            profile = extract_profile(resume_text, github_url)
            st.session_state.profile = profile

            progress_bar.progress(steps[1][1], text=steps[1][0])
            gap = analyze_gap(profile, target_role)
            st.session_state.gap = gap

            progress_bar.progress(steps[2][1], text=steps[2][0])
            roadmap = generate_roadmap(gap, target_role)
            st.session_state.roadmap = roadmap

            progress_bar.progress(steps[3][1], text=steps[3][0])
            questions = generate_interview_questions(gap, target_role)
            st.session_state.questions = questions

            progress_bar.progress(1.0, text="✅ Analysis complete!")
            time.sleep(0.5)
            progress_placeholder.empty()

        st.session_state.analysis_done = True
        
        # Determine active view/tab based on initial selection
        if career_stage == "Switcher":
             if st.session_state.get("switcher_view") == "mock":
                 st.session_state.mock_active = True
             else:
                 st.session_state.mock_active = False
        
        if career_stage == "Fresher":
            if st.session_state.get("fresher_action") == "mock":
                st.session_state.mock_active = True
            elif (st.session_state.backend_response or {}).get("mcqs"):
                st.session_state.test_active = True
        st.rerun()
 
 
# ── Fresher MCQ Test Flow ──────────────────────────────────────────────────────
def render_fresher_test():
    """Render the one-question-at-a-time MCQ test page for freshers."""
    br = st.session_state.backend_response or {}
    mcqs = br.get("mcqs", [])
    if not mcqs:
        st.warning("No MCQs available. Make sure the Flask backend is running and a PDF was uploaded.")
        if st.button("← Back to Results"):
            st.session_state.test_active = False
            st.rerun()
        return

    total   = len(mcqs)
    idx     = st.session_state.test_q_index
    answers = st.session_state.test_answers

    # ── Submitted results view ─────────────────────────────────────────────────
    if st.session_state.test_submitted:
        result = st.session_state.test_result or {}
        score  = result.get("score", sum(1 for i, q in enumerate(mcqs) if answers.get(i) == q.get("answer")))
        pct    = round(score / total * 100)
        color  = "#4ade80" if pct >= 70 else "#fbbf24" if pct >= 45 else "#f87171"

        st.markdown(f"""
        <div class="hero-header" style="text-align:center">
            <div class="hero-badge">Test Complete</div>
            <div class="hero-title" style="font-size:2.2rem">You scored {pct}%</div>
            <div class="hero-sub">// {score} correct out of {total} questions</div>
        </div>""", unsafe_allow_html=True)

        # Per-skill breakdown from backend or compute locally
        skill_ratings = result.get("skill_ratings") or (st.session_state.backend_response or {}).get("skill_ratings", {})
        if skill_ratings:
            st.markdown('<p class="section-label" style="margin-top:1rem">Your Skill Ratings</p>', unsafe_allow_html=True)
            for skill, rating in sorted(skill_ratings.items(), key=lambda x: -x[1]):
                stars = "★" * rating + "☆" * (5 - rating)
                bar_pct = rating * 20
                r_color = "#4ade80" if rating >= 4 else "#fbbf24" if rating >= 3 else "#f87171"
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.7rem">
                    <span style="font-family:'DM Mono',monospace;font-size:0.78rem;color:#9ca3af;min-width:130px">{skill}</span>
                    <div style="flex:1;background:#1e1e2e;border-radius:4px;height:6px;overflow:hidden">
                        <div style="width:{bar_pct}%;height:100%;background:{r_color};border-radius:4px"></div>
                    </div>
                    <span style="font-family:'Syne',sans-serif;font-weight:700;color:{r_color};font-size:0.85rem;min-width:30px">{rating}/5</span>
                    <span style="color:#f59e0b;font-size:0.8rem">{stars}</span>
                </div>""", unsafe_allow_html=True)

        # ── Gap Analysis View ──────────────────────────────────────────────────
        gap_analysis = result.get("gap_analysis")
        if gap_analysis and gap_analysis.get("jd_skills_required"):
            avg_comp = gap_analysis.get("avg_compensation", "N/A")
            st.markdown(f'<p class="section-label" style="margin-top:2rem">Market Readiness (Vs. 0 YOE JD) — <span style="color:#4ade80">Avg Comp: {avg_comp}</span></p>', unsafe_allow_html=True)
            
            missing = gap_analysis.get("missing_skills", [])
            matching = gap_analysis.get("matching_skills", [])
            
            mc1, mc2 = st.columns(2)
            with mc1:
                st.markdown(f"<div style='color:#4ade80; font-family:\"DM Mono\",monospace; font-size:0.8rem; margin-bottom:0.5rem;'>Matched Skills ({len(matching)})</div>", unsafe_allow_html=True)
                for s in matching:
                    st.markdown(f"<div style='background:rgba(74,222,128,0.1); border:1px solid rgba(74,222,128,0.3); color:#4ade80; padding:0.2rem 0.5rem; border-radius:4px; margin-bottom:0.3rem; font-size:0.8rem; display:inline-block; margin-right:0.3rem;'>✓ {s}</div>", unsafe_allow_html=True)
            with mc2:
                st.markdown(f"<div style='color:#f87171; font-family:\"DM Mono\",monospace; font-size:0.8rem; margin-bottom:0.5rem;'>Missing Skills ({len(missing)})</div>", unsafe_allow_html=True)
                for s in missing:
                    st.markdown(f"<div style='background:rgba(248,113,113,0.1); border:1px solid rgba(248,113,113,0.3); color:#f87171; padding:0.2rem 0.5rem; border-radius:4px; margin-bottom:0.3rem; font-size:0.8rem; display:inline-block; margin-right:0.3rem;'>✕ {s}</div>", unsafe_allow_html=True)
            
            advice = gap_analysis.get("gemini_advice")
            if advice:
                r_score = advice.get('readiness_score', 0)
                st.markdown(f'<p class="section-label" style="margin-top:2rem;color:#fcd34d">AI Readiness Score: {r_score} / 100</p>', unsafe_allow_html=True)
                
                st.markdown("**📈 Recommended Roadmap:**")
                for stp in advice.get('learning_roadmap', []):
                    st.markdown(f"- {stp}")

                st.markdown("<br>", unsafe_allow_html=True)

                st.markdown("**⚡ Fastest Way to Learn:**")
                st.info(advice.get('fastest_way_to_learn', ''))

            st.markdown("<br>", unsafe_allow_html=True)
            
            # PDF Generation Button
            try:
                pdf_bytes = generate_detail_pdf(result, pct)
                st.download_button(
                    label="📄 Download Detail Analysis (PDF)",
                    data=pdf_bytes,
                    file_name="SkillBridge_gap_analysis.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                st.markdown("<br>", unsafe_allow_html=True)
            except Exception as e:
                st.error("Error generating PDF: " + str(e))

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("← Back to Analysis", use_container_width=True):
                st.session_state.test_active    = False
                st.session_state.test_submitted  = False
                st.session_state.test_q_index   = 0
                st.session_state.test_answers   = {}
                st.rerun()
        with col_b:
            if st.button("🔄 Retake Test", use_container_width=True):
                st.session_state.test_submitted = False
                st.session_state.test_q_index  = 0
                st.session_state.test_answers  = {}
                st.rerun()
        return

    # ── Active question view ───────────────────────────────────────────────────
    q       = mcqs[idx]
    pct_val = int((idx / total) * 100)

    # Header row
    hcol1, hcol2 = st.columns([3, 1])
    with hcol1:
        st.markdown('<div class="hero-badge" style="margin-bottom:0.3rem">Fresher Skill Assessment</div>', unsafe_allow_html=True)
    with hcol2:
        if st.button("✕ Exit Test", use_container_width=True):
            st.session_state.test_active = False
            st.rerun()

    # Progress bar
    st.markdown(f"""
    <div style="margin-bottom:0.3rem;display:flex;justify-content:space-between">
        <span style="font-family:'DM Mono',monospace;font-size:0.7rem;color:#4b4b6b">PROGRESS</span>
        <span style="font-family:'DM Mono',monospace;font-size:0.7rem;color:#818cf8">Q{idx+1} / {total}</span>
    </div>
    <div class="test-progress-bar">
        <div class="test-progress-fill" style="width:{pct_val}%"></div>
    </div>
    <div style="font-family:'DM Mono',monospace;font-size:0.62rem;color:#2e2e4e;text-align:right;margin-bottom:1.5rem">{pct_val}% complete</div>
    """, unsafe_allow_html=True)

    # Question card
    skill_tag = q.get("skill", "")
    st.markdown(f"""
    <div class="test-question-card">
        <div class="test-q-number">Question {idx+1} of {total}</div>
        <div class="skill-badge">{skill_tag}</div>
        <div class="test-q-text">{q.get('question','')}</div>
    </div>
    """, unsafe_allow_html=True)

    # Options — radio auto-submits on click due to Streamlit's reactive model
    options_dict = q.get("options", {})
    options_list = [f"{k}: {v}" for k, v in options_dict.items()]
    prev_answer  = answers.get(idx)
    prev_index   = None
    if prev_answer:
        matching = [i for i, o in enumerate(options_list) if o.startswith(prev_answer + ":")]
        prev_index = matching[0] if matching else None

    st.markdown('<div class="option-hint">Select an option to continue →</div>', unsafe_allow_html=True)
    chosen = st.radio(
        f"q_{idx}",
        options_list,
        index=prev_index,
        label_visibility="collapsed",
        key=f"radio_q_{idx}"
    )

    if chosen:
        selected_key = chosen.split(":")[0].strip()   # e.g. "A"
        answers[idx] = selected_key
        st.session_state.test_answers = answers

        if idx + 1 < total:
            # Auto-advance to next question
            if st.button("Next Question →", use_container_width=True):
                st.session_state.test_q_index = idx + 1
                st.rerun()
        else:
            # Last question — show submit
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✅ Submit Test", use_container_width=True):
                submission = [
                    {
                        "question_index": i,
                        "question": mcqs[i].get("question"),
                        "skill": mcqs[i].get("skill"),
                        "selected": answers.get(i),
                        "correct": mcqs[i].get("answer"),
                        "is_correct": answers.get(i) == mcqs[i].get("answer")
                    }
                    for i in range(total)
                ]
                score_val = sum(1 for r in submission if r["is_correct"])
                try:
                    resp = http_requests.post(
                        "http://localhost:5000/api/fresher/submit-answers",
                        json={
                            "target_role": st.session_state.target_role,
                            "submission": submission,
                            "score": score_val,
                            "total": total,
                            "cv_skills": (st.session_state.backend_response or {}).get("extracted_skills", [])
                        },
                        timeout=30
                    )
                    if resp.ok:
                        st.session_state.test_result = resp.json()
                    else:
                        st.session_state.test_result = {"score": score_val}
                except:
                    st.session_state.test_result = {"score": score_val}
                st.session_state.test_submitted = True
                st.rerun()
def render_switcher_results():
    """Render the AI-powered consolidated report for switchers as soon as analysis is done."""
    br = st.session_state.backend_response or {}
    gap = br.get("gap_analysis", {})
    advice = gap.get("gemini_advice", {})
    
    avg_comp = gap.get("avg_compensation", "N/A")
    score = advice.get("readiness_score", 0)
    color = "#4ade80" if score >= 65 else "#fbbf24" if score >= 40 else "#f87171"

    # Define Dynamic Tab Order based on intent
    view = st.session_state.get("switcher_view", "gap")
    if view == "mock":
        tab_titles = [" Voice Interview", " Gap Analysis"]
    else:
        tab_titles = [" Gap Analysis", " Voice Interview"]
        
    tabs = st.tabs(tab_titles)
    gap_tab_index = 0 if view != "mock" else 1
    voice_tab_index = 1 if view != "mock" else 0

    with tabs[gap_tab_index]:
        st.markdown(f"""
        <div class="hero-header" style="text-align:center">
            <div class="hero-badge">Analysis Complete</div>
            <div class="hero-title" style="font-size:2.2rem; color:{color}">Readiness Score: {score}%</div>
            <div class="hero-sub">// Targeted Role: {st.session_state.target_role}</div>
            <div class="hero-sub" style="color:#4ade80; margin-top:0.5rem">Avg Market Comp: {avg_comp}</div>
        </div>""", unsafe_allow_html=True)
        
        st.markdown('<p class="section-label" style="margin-top:2rem">1. Transferable Skills Analysis</p>', unsafe_allow_html=True)
        st.info(advice.get("transferable_analysis", "Analyzing how your existing experience maps to the target role requirements..."))
        
        st.markdown('<p class="section-label" style="margin-top:2rem">2. Skill Presence & Gaps</p>', unsafe_allow_html=True)
        matching = gap.get("matching_skills", [])
        missing = gap.get("missing_skills", [])

        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown(f"<p style='color:#4ade80; font-family:\"DM Mono\",monospace; font-size:0.85rem; margin-bottom:0.5rem'>✓ Matched ({len(matching)})</p>", unsafe_allow_html=True)
            if matching:
                for s in matching:
                    st.markdown(f"<span class='pill pill-match' style='margin-bottom:0.5rem; display:inline-block;'>{s}</span>", unsafe_allow_html=True)
            else:
                st.markdown("<p style='color:#6b6b8a; font-size:0.8rem;'>No matching skills detected.</p>", unsafe_allow_html=True)
                
        with mc2:
            st.markdown(f"<p style='color:#f87171; font-family:\"DM Mono\",monospace; font-size:0.85rem; margin-bottom:0.5rem'>✕ Missing ({len(missing)})</p>", unsafe_allow_html=True)
            if missing:
                for s in missing:
                    st.markdown(f"<span class='pill pill-missing' style='margin-bottom:0.5rem; display:inline-block;'>{s}</span>", unsafe_allow_html=True)
            else:
                st.markdown("<p style='color:#4ade80; font-size:0.8rem;'>All required skills found!</p>", unsafe_allow_html=True)

        st.markdown('<p class="section-label" style="margin-top:2rem">3. Fastest Strategy for Career Switch</p>', unsafe_allow_html=True)
        st.success(advice.get("fastest_way_to_learn", "Prioritize hands-on projects and relevant professional certifications."))

        st.markdown("---")
        sc1, sc2 = st.columns(2)
        with sc1:
            if st.button("← New Analysis", key="switcher_new_ana", use_container_width=True):
                st.session_state.analysis_done = False
                st.rerun()
        with sc2:
            # PDF Download using the standard generator
            pdf_gen = generate_detail_pdf(br, score)
            st.download_button(
                label="📄 Download Full Analysis (PDF)",
                data=pdf_gen,
                file_name=f"Switcher_Analysis_{st.session_state.target_role}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="switcher_pdf"
            )

    with tabs[voice_tab_index]:
        st.markdown('<p class="section-label">  Audio Interview with agent', unsafe_allow_html=True)
        st.write("Practise your interview in real-time. record your response and Gemini will speak back to you natively.")
        
        # State Initialization
        if "voice_history" not in st.session_state:
            st.session_state.voice_history = []
        if "last_reply_audio" not in st.session_state:
            st.session_state.last_reply_audio = None
        if "last_reply_audio_format" not in st.session_state:
            st.session_state.last_reply_audio_format = None
        
        # Auto-start for Mock Interview intent
        auto_start = (st.session_state.get("switcher_view") == "mock" and not st.session_state.voice_history)

        use_live_streaming = st.checkbox(
            "Real-time streaming (WebSocket + Gemini Live)",
            value=False,
            help="Uses microphone chunk streaming over WebSocket. Requires backend websocket server.",
        )

        if use_live_streaming:
            context = {
                "target_role": st.session_state.target_role,
                "cv_skills": br.get("extracted_skills", []),
                "jd_skills": gap.get("jd_skills_required", []),
                "history": st.session_state.voice_history[-6:],  # past 3 turns
            }

            html = f"""
            <div style="background:#0f0f1a;border:1px solid #2e2e4e;border-radius:12px;padding:12px">
              <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                <button id="startBtn" style="padding:8px 12px;border-radius:10px;border:none;background:#6366f1;color:white;cursor:pointer">Start</button>
                <button id="stopBtn" style="padding:8px 12px;border-radius:10px;border:none;background:#6b7280;color:white;cursor:not-allowed" disabled>Stop</button>
                <span id="wsStatus" style="color:#e8e6e0;font-size:0.9rem">Idle</span>
              </div>
              <div style="margin-top:10px;color:#e8e6e0;font-size:0.95rem">
                <div><b>User:</b> <span id="userTranscript"></span></div>
                <div style="margin-top:6px"><b>Interviewer:</b> <span id="assistantTranscript"></span></div>
              </div>
              <div style="margin-top:10px;color:#a3a3b8;font-size:0.85rem">
                Streaming audio: your browser sends PCM16@16kHz chunks; Gemini responds with WAV chunks.
              </div>
            </div>

            <script>
            const WS_URL = "ws://localhost:5001/ws/switcher/mock-voice";
            const initialContext = {json.dumps(context)};

            let ws = null;
            let audioCtx = null;
            let processor = null;
            let mediaStream = null;
            let sending = false;
            let turnEndSent = false;
            let lastAudioAt = 0;
            let audioQueue = [];
            let playing = false;
            let idleTimer = null;

            const statusEl = document.getElementById("wsStatus");
            const userTranscriptEl = document.getElementById("userTranscript");
            const assistantTranscriptEl = document.getElementById("assistantTranscript");
            const startBtn = document.getElementById("startBtn");
            const stopBtn = document.getElementById("stopBtn");

            function setStatus(txt) {{
              statusEl.textContent = txt;
            }}

            function resampleFloat32(input, inputRate, outputRate) {{
              const ratio = inputRate / outputRate;
              const outputLen = Math.round(input.length / ratio);
              const output = new Float32Array(outputLen);
              for (let i = 0; i < outputLen; i++) {{
                const pos = i * ratio;
                const idx = Math.floor(pos);
                const frac = pos - idx;
                const s0 = input[idx] ?? 0;
                const s1 = input[idx + 1] ?? 0;
                output[i] = s0 + (s1 - s0) * frac;
              }}
              return output;
            }}

            function encodePCM16LE(float32) {{
              // float32 in [-1, 1] -> Int16 PCM16 little-endian bytes
              const len = float32.length;
              const int16 = new Int16Array(len);
              for (let i = 0; i < len; i++) {{
                let s = Math.max(-1, Math.min(1, float32[i]));
                int16[i] = s < 0 ? (s * 0x8000) : (s * 0x7FFF);
              }}
              const buf = new ArrayBuffer(len * 2);
              const view = new DataView(buf);
              for (let i = 0; i < len; i++) {{
                view.setInt16(i * 2, int16[i], true);
              }}
              return buf;
            }}

            function queueAndPlayWav(wavB64) {{
              audioQueue.push("data:audio/wav;base64," + wavB64);
              if (!playing) {{
                playNext();
              }}
            }}

            function playNext() {{
              if (audioQueue.length === 0) {{
                playing = false;
                return;
              }}
              playing = true;
              const url = audioQueue.shift();
              const audio = new Audio(url);
              audio.onended = () => {{
                playing = false;
                playNext();
              }};
              audio.play().catch(() => {{
                // Autoplay can be blocked; user can try again.
                playing = false;
              }});
            }}

            async function start() {{
              userTranscriptEl.textContent = "";
              assistantTranscriptEl.textContent = "";
              audioQueue = [];
              lastAudioAt = 0;
              turnEndSent = false;

              setStatus("Connecting...");
              ws = new WebSocket(WS_URL);
              ws.binaryType = "arraybuffer";

              ws.onopen = async () => {{
                setStatus("Listening (mic)...");
                ws.send(JSON.stringify({{type:"start", context: initialContext}}));

                mediaStream = await navigator.mediaDevices.getUserMedia({{audio:true}});
                // Some browsers ignore sampleRate; we still resample below to 16kHz.
                audioCtx = new (window.AudioContext || window.webkitAudioContext)({{}});
                const inputRate = audioCtx.sampleRate;

                const source = audioCtx.createMediaStreamSource(mediaStream);
                processor = audioCtx.createScriptProcessor(4096, 1, 1);
                source.connect(processor);
                processor.connect(audioCtx.destination);

                sending = true;
                processor.onaudioprocess = (e) => {{
                  if (!sending) return;
                  const ch = e.inputBuffer.getChannelData(0);
                  const resampled = (inputRate === 16000) ? ch : resampleFloat32(ch, inputRate, 16000);
                  const pcmBytes = encodePCM16LE(resampled);
                  if (ws && ws.readyState === WebSocket.OPEN) {{
                    ws.send(pcmBytes);
                  }}
                }};
              }};

              ws.onmessage = (ev) => {{
                const msg = JSON.parse(ev.data);
                if (msg.type === "assistant_audio_chunk") {{
                  lastAudioAt = Date.now();
                  queueAndPlayWav(msg.audio_wav_b64);
                }} else if (msg.type === "assistant_transcript") {{
                  assistantTranscriptEl.textContent = msg.text || "";
                }} else if (msg.type === "user_transcript") {{
                  userTranscriptEl.textContent = msg.text || "";
                }} else if (msg.type === "error") {{
                  setStatus("Error: " + (msg.error || "unknown"));
                  stopBtn.disabled = true;
                }}
              }};

              ws.onerror = () => {{
                setStatus("WebSocket error");
              }};

              ws.onclose = () => {{
                sending = false;
                stopBtn.disabled = true;
                startBtn.disabled = false;
                setStatus("Idle");
                if (idleTimer) {{
                  clearInterval(idleTimer);
                  idleTimer = null;
                }}
              }};

              stopBtn.disabled = false;
              startBtn.disabled = true;

              // Close after the assistant has finished speaking (1s idle heuristic).
              idleTimer = setInterval(() => {{
                if (turnEndSent && Date.now() - lastAudioAt > 1000 && ws && ws.readyState === WebSocket.OPEN) {{
                  ws.close();
                }}
              }}, 250);
            }}

            async function stop() {{
              turnEndSent = true;
              sending = false;
              stopBtn.disabled = true;
              setStatus("Finishing...");

              try {{
                if (ws && ws.readyState === WebSocket.OPEN) {{
                  ws.send(JSON.stringify({{type:"turn_end"}}));
                }}
              }} catch (e) {{}}

              try {{
                if (processor) {{
                  processor.disconnect();
                  processor.onaudioprocess = null;
                }}
                if (mediaStream) {{
                  mediaStream.getTracks().forEach(t => t.stop());
                }}
                if (audioCtx) {{
                  await audioCtx.close();
                }}
              }} catch (e) {{}}
            }}

            startBtn.onclick = start;
            stopBtn.onclick = stop;
            </script>
            """

            st.components.v1.html(html, height=420)
            st.stop()

        # Display history
        for msg in st.session_state.voice_history:
            role_icon = "👔" if msg["role"] == "model" else "🗣️"
            with st.chat_message(msg["role"], avatar=role_icon):
                st.markdown(msg["text"])

        # Mic Input
        voice_file = st.audio_input("Record your answer...")
        
        c1, c2 = st.columns([1, 4])
        with c1:
            start_trigger = st.button("🚀 Start / Refresh Interview", use_container_width=True)
        
        if start_trigger or auto_start or (voice_file and voice_file != st.session_state.get("last_voice_processed")):
            with st.spinner("Gemini is listening..."):
                files = {}
                if voice_file:
                    files = {"audio": ("user_voice.wav", voice_file, "audio/wav")}
                    st.session_state.last_voice_processed = voice_file
                
                context = {
                    "target_role": st.session_state.target_role,
                    "cv_skills": br.get("extracted_skills", []),
                    "jd_skills": gap.get("jd_skills_required", []),
                    "history": st.session_state.voice_history[-6:] # past 3 turns
                }
                
                BACKEND_URL = "http://localhost:5000"
                resp = http_requests.post(
                    f"{BACKEND_URL}/api/switcher/mock-voice",
                    data={"context": json.dumps(context)},
                    files=files,
                    timeout=60
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    reply_text = data.get("reply_text", "")
                    audio_b64  = data.get("reply_audio_b64")
                    
                    if not voice_file:
                        st.session_state.voice_history.append({"role": "model", "text": reply_text})
                    else:
                        st.session_state.voice_history.append({"role": "user", "text": "[Audio Input]"})
                        st.session_state.voice_history.append({"role": "model", "text": reply_text})
                    
                    if audio_b64:
                        st.session_state.last_reply_audio = audio_b64
                        st.session_state.last_reply_audio_format = data.get("audio_format")
                    
                    st.rerun()
                else:
                    # Surface backend errors immediately so the user isn't left with silence.
                    err_txt = None
                    try:
                        err_txt = (resp.json() or {}).get("error")
                    except Exception:
                        err_txt = resp.text
                    st.error(f"Mock interview failed ({resp.status_code}): {err_txt or 'Unknown error'}")

        # Audio Playback
        if st.session_state.last_reply_audio:
            fmt = st.session_state.last_reply_audio_format or "mp3"
            mime = "audio/mp3" if fmt == "mp3" else "audio/wav" if fmt == "wav" else "audio/mp3"
            st.audio(base64.b64decode(st.session_state.last_reply_audio), format=mime, autoplay=True)

        if st.session_state.voice_history:
            if st.button("🗑️ Clear Interview", use_container_width=True):
                st.session_state.voice_history = []
                st.session_state.last_reply_audio = None
                st.session_state.last_reply_audio_format = None
                st.rerun()



# ── Results ────────────────────────────────────────────────────────────────────
if st.session_state.analysis_done:
    # ── Show Fresher / Switcher specialized views ──────────────────────────────────────
    if st.session_state.career_stage == "Fresher" and st.session_state.get("mock_active"):
        # Keep the UI focused: when Fresher "mock" is selected, we still show gap analysis.
        # The "AI Mock Interview Questions" page is removed from the gap analysis view.
        st.session_state.mock_active = False

    elif st.session_state.career_stage == "Fresher" and st.session_state.test_active:
        render_fresher_test()
        st.stop()
        
    elif st.session_state.career_stage == "Switcher":
        render_switcher_results()
        st.stop()

    if st.button("← Start New Analysis"):
        st.session_state.analysis_done   = False
        st.session_state.profile         = None
        st.session_state.gap             = None
        st.session_state.roadmap         = None
        st.session_state.questions       = None
        st.session_state.test_active     = False
        st.session_state.test_q_index    = 0
        st.session_state.test_answers    = {}
        st.session_state.test_submitted  = False
        st.session_state.test_result     = None
        st.session_state.backend_response = None
        st.rerun()

    profile   = st.session_state.profile
    gap       = st.session_state.gap
    roadmap   = st.session_state.roadmap
    questions = st.session_state.questions
    role      = st.session_state.target_role
 
    # Profile summary strip
    score = gap.get("match_score", 0)
    color = "#4ade80" if score >= 65 else "#fbbf24" if score >= 40 else "#f87171"
    st.markdown(f"""
    <div class="card" style="border-left:3px solid #6366f1;margin-bottom:1.5rem">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
                <div style="font-family:'Syne',sans-serif;font-weight:800;font-size:1.1rem;color:#fff">
                    {profile.get('name','Your Profile')}
                </div>
                <div style="font-family:'DM Mono',monospace;font-size:0.75rem;color:#6b6b8a;margin-top:0.2rem">
                    {profile.get('summary','')}
                </div>
            </div>
            <div style="text-align:right">
                <div style="font-family:'Syne',sans-serif;font-size:0.75rem;font-weight:600;color:#6b6b8a;
                     text-transform:uppercase;letter-spacing:0.08em">Target Role</div>
                <div style="font-family:'Syne',sans-serif;font-weight:800;font-size:1rem;
                     color:#818cf8">{role}</div>
                <div style="font-family:'DM Mono',monospace;font-size:0.68rem;color:#4b4b6b;margin-top:0.25rem">
                    Stage: {st.session_state.get('career_stage','—')}
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
 
    # Tabs
    tab1, tab2, tab3 = st.tabs(["  📊 Gap Analysis  ", "  🗺️ Learning Roadmap  ", "  🎤 Mock Interview  "])
 
    with tab1:
        render_gap_dashboard(gap, role)
 
    with tab2:
        render_roadmap(roadmap)
 
    with tab3:
        st.markdown("""
        <div class="info-box" style="margin-bottom:1.5rem">
            🎤 Questions are tailored to your specific gaps for <strong>{}</strong>.
            Practice these before interviews to stand out.
        </div>""".format(role), unsafe_allow_html=True)
        
        if st.session_state.career_stage == "Fresher" and (st.session_state.backend_response or {}).get("mcqs"):
            st.markdown("""
            <div style="background:#111118; border:1px solid #2e2e4e; border-radius:8px; padding:1.5rem; text-align:center; margin-bottom:1.5rem;">
                <h3 style="margin-top:0; color:#fff; font-family:'Syne',sans-serif;">Take Your Skill Assessment</h3>
                <p style="color:#6b6b8a; font-size:0.9rem; margin-bottom:1rem;">Evaluate your true proficiency with 10 high-quality MCQs generated from your resume. Your skill ratings will be updated based on your score!</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("📝 Start MCQ Assessment", use_container_width=True):
                st.session_state.test_active = True
                st.rerun()
            st.markdown("---")

        render_interview_prep(questions)
 
# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="margin-bottom:1.5rem;padding:0.8rem;background:#0a0a14;border-radius:8px;
     border:1px solid #1e1e2e">
    <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#4b4b6b;
         text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.5rem">
    </div>
    <div style="font-size:0.75rem;color:#4b4b6b;line-height:1.5">
        Job market insights are AI-generated and should be independently verified.
        Course recommendations are suggestions to explore, not guarantees of outcomes
    </div>
</div>
<div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#2e2e4e;
     text-align:center;padding:0.5rem">
    SKILL-BRIDGE CAREER NAVIGATOR &nbsp;·&nbsp;
</div>
""", unsafe_allow_html=True)