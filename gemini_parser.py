import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables (particularly GEMINI_API_KEY from .env)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def parse_cv_with_gemini(pdf_bytes: bytes) -> str:
    """
    Takes raw PDF bytes and uses Gemini 3 Flash's native PDF understanding
    to structure it focusing on Skills, Experience, Projects, and Certifications.
    """
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not found in environment. Cannot parse PDF natively.")
        return ""
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = """
        You are an expert technical recruiter and resume parser.
        I have attached a candidate's resume in PDF format.
        Please read through it and extract the information, structuring it beautifully in plain text format (with bullet points and neat headings). 
        
        Focus EXACTLY on extracting and organizing these 4 sections:
        1. Skills
        2. Experience
        3. Projects
        4. Certifications
        
        Return ONLY the newly parsed information under those headings. Omit any long summaries or irrelevant fluff.
        If a section is missing from the curriculum vitae, just indicate "None found."
        """
        
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                prompt
            ]
        )
        
        # Log to the backend console
        print("\n" + "="*40)
        print(" Gemini Parsed CV Result (Backend Execution):")
        print("="*40)
        print(response.text)
        print("="*40 + "\n")
        
        return response.text
        
    except Exception as e:
        print(f"Error using Gemini API: {e}")
        return ""
