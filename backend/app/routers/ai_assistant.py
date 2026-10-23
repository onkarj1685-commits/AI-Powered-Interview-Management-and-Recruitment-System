import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-flash-latest"


class AskQuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question asked by the candidate or interviewer")
    context: Optional[str] = Field(None, description="Optional interview/candidate/job context")
    role: Optional[str] = Field("candidate", description="Target perspective: 'candidate' or 'interviewer'")


class AskQuestionResponse(BaseModel):
    answer: str
    model: str


class GenerateQuestionsRequest(BaseModel):
    job_title: str = Field(..., min_length=1, description="Job title for question generation")
    department: Optional[str] = None
    round_name: Optional[str] = None
    experience_level: Optional[str] = None


class GenerateQuestionsResponse(BaseModel):
    questions: list[str]
    raw_response: str
    model: str


def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key or key == "your_gemini_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API key is not configured. Please set GEMINI_API_KEY in .env",
        )
    return key


async def call_gemini_generate(prompt: str, system_instruction: Optional[str] = None) -> str:
    key = get_gemini_api_key()

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    if system_instruction:
        payload["system_instruction"] = {
            "parts": [{"text": system_instruction}]
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try primary model first, fallback if needed
        for model in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                    return "No answer could be generated. Please rephrase your question."
                elif resp.status_code == 404:
                    # Try fallback model
                    continue
                else:
                    detail_msg = resp.text
                    try:
                        err_json = resp.json()
                        detail_msg = err_json.get("error", {}).get("message", detail_msg)
                    except Exception:
                        pass
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"Gemini API error ({resp.status_code}): {detail_msg}",
                    )
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Unable to reach Gemini API: {str(e)}",
                )

    raise HTTPException(status_code=500, detail="Failed to generate content with available Gemini models")


@router.get("/status")
def get_ai_status():
    """Check if Gemini AI assistance is configured and available."""
    key = os.getenv("GEMINI_API_KEY")
    is_configured = bool(key and key != "your_gemini_api_key_here")
    return {
        "configured": is_configured,
        "model": GEMINI_MODEL,
        "service": "Google Gemini AI",
    }


@router.post("/ask", response_model=AskQuestionResponse)
async def ask_ai_question(payload: AskQuestionRequest):
    """Answer candidate or interviewer interview questions using Gemini."""
    system_instruction = (
        "You are an expert AI Interview & Hiring Coach for the AI-Powered Interview Management and Recruitment System. "
        "You help candidates prepare for interviews, answer difficult technical and behavioral questions, "
        "explain concepts with clarity, and provide actionable tips using methods like STAR. "
        "Keep your answers well-structured, clear, professional, and encouraging. Use bullet points and code examples where helpful."
    )

    context_str = f"\nAdditional Context: {payload.context}" if payload.context else ""
    prompt = (
        f"Perspective: {payload.role.capitalize()}\n"
        f"Question / Query: {payload.question}"
        f"{context_str}\n\n"
        "Please provide a comprehensive, clear, and helpful answer for the interview scenario."
    )

    answer = await call_gemini_generate(prompt, system_instruction=system_instruction)
    return AskQuestionResponse(answer=answer, model=GEMINI_MODEL)


@router.post("/generate-questions", response_model=GenerateQuestionsResponse)
async def generate_interview_questions(payload: GenerateQuestionsRequest):
    """Generate tailored interview questions for a specific job position and round."""
    system_instruction = (
        "You are a Senior Technical Recruiter and Hiring Manager. "
        "Generate 5 to 7 high-quality, practical interview questions tailored for the given role, department, and round. "
        "Return each question on a new line prefixed with a number (e.g., '1. ...')."
    )

    prompt = (
        f"Job Title: {payload.job_title}\n"
        f"Department: {payload.department or 'General'}\n"
        f"Interview Round: {payload.round_name or 'Technical Interview'}\n"
        f"Experience Level: {payload.experience_level or 'Mid-level'}\n\n"
        "Generate 5 targeted interview questions with brief guidance on what the interviewer should look for in answers."
    )

    raw_text = await call_gemini_generate(prompt, system_instruction=system_instruction)

    # Extract individual questions
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    questions = []
    for line in lines:
        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
            questions.append(line.lstrip("0123456789.-* "))

    return GenerateQuestionsResponse(
        questions=questions if questions else [raw_text],
        raw_response=raw_text,
        model=GEMINI_MODEL,
    )
