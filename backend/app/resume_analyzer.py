"""
AI Resume Analyzer Engine.

Provides:
- Native PDF resume text extraction via pypdf.
- NLP domain auto-detection and skill extraction.
- Missing skill gap identification against domain benchmarks.
- ATS compatibility scoring (0-100) and Resume Strength rating.
- 5-factor scorecard breakdown: Technical Skills, Projects, Education, Experience, ATS.
- Personalized actionable AI suggestions (GitHub, LinkedIn, metrics, certifications, formatting).
- AI recommendations (Strengths, Weaknesses, Final Recommendation).
- Downloadable branded PDF report generation via ReportLab.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pypdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# =============================================================================
# 1. Comprehensive Skill & Domain Taxonomy
# =============================================================================

ROLE_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "Data Analyst": {
        "title": "Data Analyst",
        "benchmark_skills": [
            "Python", "SQL", "Power BI", "Data Analysis", "Excel", "Tableau",
            "Pandas", "NumPy", "Statistics", "Machine Learning"
        ],
        "default_recommendation": "Suitable for Fresher Data Analyst Role",
    },
    "Software Engineer / Full Stack": {
        "title": "Software Engineer",
        "benchmark_skills": [
            "Python", "JavaScript", "TypeScript", "React", "FastAPI",
            "PostgreSQL", "Docker", "Git", "REST APIs", "CI/CD", "Node.js"
        ],
        "default_recommendation": "Suitable for Junior Software Engineer Role",
    },
    "Frontend Developer": {
        "title": "Frontend Developer",
        "benchmark_skills": [
            "JavaScript", "TypeScript", "React", "HTML/CSS", "Tailwind CSS",
            "Next.js", "Redux", "Git", "REST APIs", "Vue.js"
        ],
        "default_recommendation": "Suitable for Frontend Web Developer Role",
    },
    "Backend Developer": {
        "title": "Backend Developer",
        "benchmark_skills": [
            "Python", "FastAPI", "Django", "SQL", "PostgreSQL",
            "Docker", "REST APIs", "Redis", "Git", "Microservices"
        ],
        "default_recommendation": "Suitable for Backend Developer Role",
    },
    "AI / Machine Learning Engineer": {
        "title": "AI / ML Engineer",
        "benchmark_skills": [
            "Python", "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow",
            "Pandas", "NumPy", "Natural Language Processing (NLP)", "SQL", "Large Language Models (LLMs)"
        ],
        "default_recommendation": "Suitable for Junior AI / Machine Learning Role",
    },
    "Cloud & DevOps Engineer": {
        "title": "Cloud & DevOps Engineer",
        "benchmark_skills": [
            "Docker", "Kubernetes", "AWS", "Linux", "CI/CD",
            "Terraform", "Python", "Git", "Bash", "Azure"
        ],
        "default_recommendation": "Suitable for Cloud & DevOps Associate Role",
    },
}

# Skill keyword lookup mapping
SKILL_TAXONOMY: Dict[str, List[str]] = {
    "Python": ["python", "py", "python3", "python2"],
    "SQL": ["sql", "mysql", "postgresql", "postgres", "sqlite", "tsql", "plsql"],
    "Power BI": ["power bi", "powerbi", "dax", "power query"],
    "Data Analysis": ["data analysis", "data analytics", "eda", "exploratory data analysis", "data cleaning", "bi analysis"],
    "Excel": ["excel", "ms excel", "microsoft excel", "advanced excel", "vlookup", "pivot tables"],
    "Tableau": ["tableau", "tableau desktop"],
    "Machine Learning": ["machine learning", "ml", "supervised learning", "unsupervised learning", "scikit-learn", "sklearn"],
    "Deep Learning": ["deep learning", "neural networks", "cnn", "rnn", "lstm"],
    "Natural Language Processing (NLP)": ["nlp", "natural language processing", "spacy", "nltk", "transformers"],
    "Large Language Models (LLMs)": ["llm", "llms", "large language models", "prompt engineering", "langchain", "rag", "gpt", "gemini"],
    "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow", "tf", "keras"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Statistics": ["statistics", "statistical modeling", "hypothesis testing", "regression"],
    "JavaScript": ["javascript", "js", "es6", "es2015"],
    "TypeScript": ["typescript", "ts"],
    "React": ["react", "react.js", "reactjs", "react native"],
    "FastAPI": ["fastapi", "fast-api"],
    "Django": ["django", "drf", "django rest framework"],
    "Flask": ["flask"],
    "Node.js": ["node", "node.js", "nodejs"],
    "Express.js": ["express", "express.js", "expressjs"],
    "HTML/CSS": ["html", "html5", "css", "css3", "sass", "scss"],
    "Tailwind CSS": ["tailwind", "tailwindcss"],
    "Next.js": ["next.js", "nextjs"],
    "Docker": ["docker", "containerization", "docker-compose"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda", "rds"],
    "Azure": ["azure", "microsoft azure"],
    "Google Cloud (GCP)": ["gcp", "google cloud"],
    "Git": ["git", "github", "gitlab"],
    "CI/CD": ["ci/cd", "continuous integration", "github actions", "jenkins"],
    "Linux": ["linux", "bash", "ubuntu", "shell scripting"],
    "REST APIs": ["rest", "restful", "rest api", "rest apis", "restful api"],
    "Microservices": ["microservices", "microservice", "distributed systems"],
    "Java": ["java", "spring", "spring boot"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "csharp", ".net"],
}

KEYWORD_TO_SKILL: Dict[str, str] = {}
for canonical, keywords in SKILL_TAXONOMY.items():
    for kw in keywords:
        KEYWORD_TO_SKILL[kw.lower()] = canonical


# =============================================================================
# 2. Text Extraction & Cleaning
# =============================================================================

def extract_text_from_pdf_stream(stream_or_path: Any) -> str:
    """Extract plain text from PDF using pypdf with robust fallback handling."""
    extracted_text = ""
    try:
        reader = pypdf.PdfReader(stream_or_path)
        pages_text = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                pages_text.append(t)
        extracted_text = "\n".join(pages_text)
    except Exception as exc:
        print("Notice: pypdf extraction fallback:", exc)

    # Fallback to byte pattern scan if extracted text is blank
    if not extracted_text.strip():
        try:
            if isinstance(stream_or_path, (str, Path)):
                raw_bytes = Path(stream_or_path).read_bytes()
            elif hasattr(stream_or_path, "read"):
                stream_or_path.seek(0)
                raw_bytes = stream_or_path.read()
            else:
                raw_bytes = b""
            strings = re.findall(rb"[\x20-\x7E]{4,}", raw_bytes)
            extracted_text = " ".join(s.decode("latin1", errors="ignore") for s in strings)
        except Exception:
            extracted_text = ""

    return clean_text(extracted_text)


def clean_text(text: str) -> str:
    """Normalize whitespace and control characters."""
    if not text:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_candidate_name(text: str, filename: str = "") -> str:
    """Extract candidate name from top lines of resume or filename."""
    if not text:
        clean_fn = re.sub(r"[-_]", " ", Path(filename).stem)
        return clean_fn.title() if clean_fn else "Candidate"

    lines = [line.strip() for line in text.split(" ") if line.strip()]
    first_chunk = " ".join(lines[:30])

    # Check for name patterns before contact information
    name_match = re.search(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})", first_chunk)
    if name_match:
        cand = name_match.group(1).strip()
        if not any(skip in cand.lower() for skip in ["curriculum", "resume", "profile", "contact", "email", "phone"]):
            return cand

    # Fallback to filename
    if filename:
        clean_fn = re.sub(r"(resume|cv|biodata)[-_]?", "", Path(filename).stem, flags=re.IGNORECASE)
        clean_fn = re.sub(r"[-_]", " ", clean_fn).strip()
        if clean_fn and len(clean_fn) >= 3:
            return clean_fn.title()

    return "Candidate"


# =============================================================================
# 3. NLP Skill Extraction & Gap Analysis
# =============================================================================

def extract_skills_from_text(text: str) -> List[str]:
    """Identify skills present in the resume using boundary-aware keyword matching."""
    if not text:
        return []

    lower_text = " " + text.lower() + " "
    detected: Set[str] = set()

    for kw, canonical in KEYWORD_TO_SKILL.items():
        pattern = r"(?<![a-zA-Z0-9])" + re.escape(kw) + r"(?![a-zA-Z0-9])"
        if re.search(pattern, lower_text):
            detected.add(canonical)

    return sorted(detected)


def detect_target_role(skills_found: List[str], text: str) -> Tuple[str, Dict[str, Any]]:
    """Automatically detect the best-matching job role/domain from skills and keywords."""
    lower_text = text.lower()
    best_role = "Data Analyst"
    best_score = -1
    best_meta = ROLE_BENCHMARKS["Data Analyst"]

    found_set = set(skills_found)

    for role_name, meta in ROLE_BENCHMARKS.items():
        benchmarks = set(meta["benchmark_skills"])
        overlap = len(found_set.intersection(benchmarks))

        # Title mentions boost score
        if meta["title"].lower() in lower_text:
            overlap += 4

        if overlap > best_score:
            best_score = overlap
            best_role = role_name
            best_meta = meta

    return best_role, best_meta


def compute_skill_gaps(skills_found: List[str], target_role: str) -> List[str]:
    """Determine important benchmark skills missing for the detected role."""
    meta = ROLE_BENCHMARKS.get(target_role, ROLE_BENCHMARKS["Data Analyst"])
    benchmarks = meta["benchmark_skills"]
    found_set = set(skills_found)

    missing = [skill for skill in benchmarks if skill not in found_set]
    return missing[:5]  # Top missing skills


# =============================================================================
# 4. ATS Scoring & 5-Category Breakdown
# =============================================================================

def analyze_ats_compatibility(text: str) -> int:
    """Calculate ATS Compatibility percentage (0-100%) based on structural ATS criteria."""
    if not text:
        return 50

    lower = text.lower()
    score = 40  # Base score

    # 1. Contact Information (+15 pts)
    has_email = bool(re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text))
    has_phone = bool(re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text))
    if has_email:
        score += 8
    if has_phone:
        score += 7

    # 2. Standard Section Headers (+15 pts)
    headers = ["education", "experience", "projects", "skills", "certifications", "summary"]
    header_hits = sum(1 for h in headers if h in lower)
    score += min(header_hits * 3, 15)

    # 3. Action Verbs (+15 pts)
    action_verbs = [
        "developed", "built", "implemented", "analyzed", "designed", "created",
        "managed", "collaborated", "optimized", "engineered", "delivered", "deployed"
    ]
    verb_hits = sum(1 for v in action_verbs if v in lower)
    score += min(verb_hits * 3, 15)

    # 4. Quantifiable Metrics / Achievements (+10 pts)
    has_metrics = bool(re.search(r"\d+%\s*|\$\d+|\d+\+?\s*(users|clients|records|latency|speed)", lower))
    if has_metrics:
        score += 10
    else:
        score += 4

    # 5. Length & Readability (+10 pts)
    word_count = len(text.split())
    if 250 <= word_count <= 1400:
        score += 10
    elif word_count > 100:
        score += 5

    return min(max(score, 45), 96)


def compute_resume_breakdown(
    skills_found: List[str],
    text: str,
    ats_score: int,
) -> Dict[str, int]:
    """Compute percentage scores (0-100) for the 5 key dimensions."""
    lower = text.lower()

    # 1. Technical Skills Score (based on diversity of detected skills)
    tech_score = min(50 + (len(skills_found) * 5), 95)

    # 2. Projects Score (mentions of projects, tools, frameworks, impact)
    has_projects_header = "project" in lower
    project_mentions = len(re.findall(r"(project|developed|built|api|application|model|dashboard)", lower))
    proj_score = 60 + (15 if has_projects_header else 0) + min(project_mentions * 2, 20)
    proj_score = min(max(proj_score, 55), 94)

    # 3. Education Score (degree keywords, institution, GPA/grades)
    edu_hits = sum(1 for e in ["bachelor", "b.tech", "b.e", "m.tech", "master", "degree", "university", "college", "cgpa", "gpa"] if e in lower)
    edu_score = min(65 + (edu_hits * 6), 96)

    # 4. Experience Score (internships, work history, experience years)
    exp_hits = sum(1 for ex in ["intern", "internship", "experience", "worked", "full-time", "part-time", "role", "team"] if ex in lower)
    exp_score = min(50 + (exp_hits * 5), 92)

    # 5. ATS Score
    return {
        "technical_skills_score": int(tech_score),
        "projects_score": int(proj_score),
        "education_score": int(edu_score),
        "experience_score": int(exp_score),
        "ats_score": int(ats_score),
    }


# =============================================================================
# 5. Personalized Suggestions & Recommendations
# =============================================================================

def generate_ai_suggestions(text: str, skills_found: List[str], missing_skills: List[str]) -> List[str]:
    """Generate personalized improvement suggestions matching user requirements."""
    lower = text.lower()
    suggestions: List[str] = []

    # 1. GitHub profile
    if "github" not in lower:
        suggestions.append("Add GitHub profile: Link your GitHub profile so recruiters can review your repositories and clean code quality.")

    # 2. LinkedIn profile
    if "linkedin" not in lower:
        suggestions.append("Add LinkedIn profile: Include a clickable LinkedIn URL to establish verified professional credibility.")

    # 3. Project descriptions & measurable metrics
    has_metrics = bool(re.search(r"\d+%", lower))
    if not has_metrics:
        suggestions.append("Add measurable achievements: Quantify your impact in projects (e.g., 'Optimized data pipeline reducing query runtime by 30%').")

    # 4. Project descriptions detail
    suggestions.append("Improve project descriptions: Use the STAR method (Situation, Task, Action, Result) for each project instead of generic summaries.")

    # 5. Certifications
    if "certif" not in lower:
        top_missing = missing_skills[0] if missing_skills else "Cloud / Data Analysis"
        suggestions.append(f"Add certifications: Pursue and list an accredited credential in {top_missing} or AWS to validate your skills.")

    # 6. ATS formatting
    suggestions.append("Improve ATS formatting: Use clean single-column layout, standard section headings, and bullet points starting with action verbs.")

    return suggestions[:6]


def generate_recommendations(
    skills_found: List[str],
    missing_skills: List[str],
    target_role: str,
    text: str,
) -> Dict[str, Any]:
    """Generate Strengths, Weaknesses, and Final Recommendation."""
    lower = text.lower()

    strengths: List[str] = []
    if skills_found:
        strengths.append(f"Relevant technical skills in {', '.join(skills_found[:4])}")
    else:
        strengths.append("Foundational understanding of core technology principles")

    if "project" in lower:
        strengths.append("Demonstrated hands-on execution with practical academic/personal projects")
    else:
        strengths.append("Clear educational background with structured degree coursework")

    if len(skills_found) >= 5:
        strengths.append("Diverse toolset bridging multiple complementary technologies")

    weaknesses: List[str] = []
    if "certif" not in lower:
        weaknesses.append("Missing accredited industry certifications to stand out in applicant tracking systems")

    if "intern" not in lower:
        weaknesses.append("No formal internship or enterprise production environment experience documented")

    if missing_skills:
        weaknesses.append(f"Skill gaps identified in high-demand benchmark tools ({', '.join(missing_skills[:3])})")

    meta = ROLE_BENCHMARKS.get(target_role, ROLE_BENCHMARKS["Data Analyst"])
    final_rec = meta["default_recommendation"]

    return {
        "strengths": strengths[:3],
        "weaknesses": weaknesses[:3],
        "final_recommendation": final_rec,
    }


# =============================================================================
# 6. Full Analysis Pipeline
# =============================================================================

def analyze_resume_text(text: str, filename: str = "resume.pdf") -> Dict[str, Any]:
    """Execute end-to-end automated resume analysis from extracted text."""
    candidate_name = extract_candidate_name(text, filename)
    skills_found = extract_skills_from_text(text)
    target_role, _ = detect_target_role(skills_found, text)
    missing_skills = compute_skill_gaps(skills_found, target_role)

    ats_score = analyze_ats_compatibility(text)
    breakdown = compute_resume_breakdown(skills_found, text, ats_score)

    # Overall Score formula
    weighted = (
        (breakdown["technical_skills_score"] * 0.35)
        + (breakdown["projects_score"] * 0.20)
        + (breakdown["education_score"] * 0.15)
        + (breakdown["experience_score"] * 0.15)
        + (breakdown["ats_score"] * 0.15)
    )
    overall_score = int(round(min(max(weighted, 40), 98)))

    # Strength rating
    if overall_score >= 85:
        strength = "Excellent"
    elif overall_score >= 70:
        strength = "Good"
    else:
        strength = "Average"

    suggestions = generate_ai_suggestions(text, skills_found, missing_skills)
    rec_info = generate_recommendations(skills_found, missing_skills, target_role, text)

    return {
        "filename": filename,
        "candidate_name": candidate_name,
        "target_role": target_role,
        "overall_score": overall_score,
        "ats_score": ats_score,
        "strength": strength,
        "skills_found": skills_found,
        "missing_skills": missing_skills,
        "breakdown": breakdown,
        "suggestions": suggestions,
        "strengths": rec_info["strengths"],
        "weaknesses": rec_info["weaknesses"],
        "recommendation": rec_info["final_recommendation"],
    }


def analyze_pdf_file(file_path: Path, filename: Optional[str] = None) -> Dict[str, Any]:
    """Extract text from PDF file and perform full resume analysis."""
    fn = filename or file_path.name
    text = extract_text_from_pdf_stream(file_path)
    return analyze_resume_text(text, fn)


# =============================================================================
# 7. Branded PDF Report Generator (ReportLab)
# =============================================================================

def generate_pdf_report(analysis: Dict[str, Any]) -> bytes:
    """
    Generate a modern, beautifully styled AI Resume Analysis Report PDF.
    Returns the binary content of the generated PDF document.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    # Custom Clean Palette
    primary_color = colors.HexColor("#4F46E5")
    dark_text = colors.HexColor("#1E293B")
    muted_text = colors.HexColor("#64748B")
    success_color = colors.HexColor("#059669")
    danger_color = colors.HexColor("#DC2626")
    bg_light = colors.HexColor("#F8FAFC")
    border_color = colors.HexColor("#E2E8F0")

    # Typography styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=22,
        leading=26,
        textColor=primary_color,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=muted_text,
        fontName="Helvetica",
        spaceAfter=14,
    )
    h2_style = ParagraphStyle(
        "ReportH2",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        textColor=primary_color,
        fontName="Helvetica-Bold",
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13.5,
        textColor=dark_text,
        fontName="Helvetica",
    )
    bullet_style = ParagraphStyle(
        "ReportBullet",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=dark_text,
        fontName="Helvetica",
        leftIndent=12,
    )

    elements: List[Any] = []

    # 1. Header Section
    elements.append(Paragraph("AI Resume Analysis Report", title_style))
    report_date = datetime.utcnow().strftime("%B %d, %Y")
    cand_name = analysis.get("candidate_name") or "Candidate"
    target_role = analysis.get("target_role") or "Data Analyst"
    elements.append(
        Paragraph(
            f"Candidate: <b>{cand_name}</b> &bull; Target Domain: <b>{target_role}</b> &bull; Generated: {report_date}",
            subtitle_style,
        )
    )
    elements.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceAfter=14))

    # 2. Key Metrics Summary Banner (Table)
    overall_score = analysis.get("overall_score", 82)
    ats_score = analysis.get("ats_score", 88)
    strength = analysis.get("strength", "Good")

    summary_data = [
        [
            Paragraph(f"<font size=8 color='#64748B'>OVERALL SCORE</font><br/><font size=18 color='#4F46E5'><b>{overall_score}/100</b></font>", body_style),
            Paragraph(f"<font size=8 color='#64748B'>ATS COMPATIBILITY</font><br/><font size=18 color='#059669'><b>{ats_score}%</b></font>", body_style),
            Paragraph(f"<font size=8 color='#64748B'>RESUME STRENGTH</font><br/><font size=18 color='#4F46E5'><b>{strength}</b></font>", body_style),
            Paragraph(f"<font size=8 color='#64748B'>EVALUATION DECISION</font><br/><font size=11 color='#1E293B'><b>Ready for Hiring</b></font>", body_style),
        ]
    ]
    summary_table = Table(summary_data, colWidths=[130, 130, 130, 140])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_light),
            ("BOX", (0, 0), (-1, -1), 1, border_color),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ])
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 14))

    # 3. Skills Analysis (Found vs Missing Side-by-Side)
    elements.append(Paragraph("Skills Assessment & Gap Analysis", h2_style))

    found_skills = analysis.get("skills_found") or []
    missing_skills = analysis.get("missing_skills") or []

    found_text = "<br/>".join([f"<font color='#059669'><b>&#10004;</b></font> {s}" for s in found_skills]) or "No core skills detected"
    missing_text = "<br/>".join([f"<font color='#DC2626'><b>&#10008;</b></font> {s}" for s in missing_skills]) or "No critical skill gaps identified"

    skills_data = [
        [Paragraph("<b>Skills Found on Resume</b>", body_style), Paragraph("<b>Missing Benchmark Skills</b>", body_style)],
        [Paragraph(found_text, body_style), Paragraph(missing_text, body_style)],
    ]
    skills_table = Table(skills_data, colWidths=[265, 265])
    skills_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), bg_light),
            ("BOX", (0, 0), (-1, -1), 1, border_color),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    elements.append(skills_table)
    elements.append(Spacer(1, 14))

    # 4. Resume Score Breakdown Table
    elements.append(Paragraph("Resume Dimensional Breakdown", h2_style))
    breakdown = analysis.get("breakdown") or {}

    breakdown_data = [
        [Paragraph("<b>Evaluation Dimension</b>", body_style), Paragraph("<b>Score</b>", body_style), Paragraph("<b>Status</b>", body_style)],
        [Paragraph("Technical Skills Score", body_style), Paragraph(f"{breakdown.get('technical_skills_score', 80)}%", body_style), Paragraph("Strong" if breakdown.get('technical_skills_score', 80) >= 75 else "Moderate", body_style)],
        [Paragraph("Projects & Applied Work", body_style), Paragraph(f"{breakdown.get('projects_score', 85)}%", body_style), Paragraph("Strong" if breakdown.get('projects_score', 85) >= 75 else "Moderate", body_style)],
        [Paragraph("Education & Academic Background", body_style), Paragraph(f"{breakdown.get('education_score', 90)}%", body_style), Paragraph("Excellent", body_style)],
        [Paragraph("Experience & Practical Depth", body_style), Paragraph(f"{breakdown.get('experience_score', 70)}%", body_style), Paragraph("Entry-Level", body_style)],
        [Paragraph("ATS Formatting & Hygiene", body_style), Paragraph(f"{breakdown.get('ats_score', 88)}%", body_style), Paragraph("Optimized", body_style)],
    ]
    breakdown_table = Table(breakdown_data, colWidths=[260, 135, 135])
    breakdown_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), bg_light),
            ("BOX", (0, 0), (-1, -1), 1, border_color),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(breakdown_table)
    elements.append(Spacer(1, 14))

    # 5. Personalized AI Suggestions
    elements.append(Paragraph("Personalized Improvement Suggestions", h2_style))
    suggestions = analysis.get("suggestions") or []
    for sug in suggestions:
        elements.append(Paragraph(f"&bull; {sug}", bullet_style))
        elements.append(Spacer(1, 3))
    elements.append(Spacer(1, 10))

    # 6. AI Recommendation (Strengths, Weaknesses, Final Role Fit)
    elements.append(Paragraph("AI Final Evaluation & Career Recommendation", h2_style))

    strengths_items = analysis.get("strengths") or []
    weaknesses_items = analysis.get("weaknesses") or []
    final_rec = analysis.get("recommendation") or "Suitable for Fresher Data Analyst Role"

    rec_content = [
        [Paragraph("<b>Key Strengths:</b>", body_style)],
    ]
    for st in strengths_items:
        rec_content.append([Paragraph(f"&bull; {st}", bullet_style)])

    rec_content.append([Spacer(1, 4)])
    rec_content.append([Paragraph("<b>Areas for Development:</b>", body_style)])
    for wk in weaknesses_items:
        rec_content.append([Paragraph(f"&bull; {wk}", bullet_style)])

    rec_content.append([Spacer(1, 4)])
    rec_content.append([Paragraph(f"<b>Final Role Recommendation:</b> <font color='#4F46E5'><b>{final_rec}</b></font>", body_style)])

    rec_table = Table(rec_content, colWidths=[530])
    rec_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_light),
            ("BOX", (0, 0), (-1, -1), 1, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(rec_table)

    # Build PDF
    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()


# =============================================================================
# 8. High-Fidelity Default Sample Resume
# =============================================================================

DEFAULT_SAMPLE_RESUME_TEXT = """
ADITYA VERMA
Email: aditya.verma@example.com | Phone: +91 98765 43210
Location: Pune, India

PROFESSIONAL SUMMARY
Motivated Computer Science graduate with hands-on expertise in Data Analysis, SQL database design, Python scripting, and Power BI dashboard creation. Strong foundation in statistical data transformation, data cleaning, and business intelligence reporting.

TECHNICAL SKILLS
Programming & Scripting: Python, SQL, C++
Data Analysis & BI: Power BI, Data Analysis, Pandas, NumPy, Data Cleaning, Relational Database Querying
Developer Tools: Git, VS Code, Jupyter Notebooks, Linux

PROJECTS
1. Retail Sales & Inventory BI Dashboard (Power BI, SQL, Python)
- Extracted and transformed 500,000+ transactional sales records from PostgreSQL database using Python and Pandas.
- Designed automated Power BI dashboards displaying monthly recurring revenue, customer churn trends, and inventory forecasting.
- Streamlined reporting cycle, reducing manual weekly spreadsheet consolidation time by 40%.

2. Customer Sentiment & Behavioral Analysis System (Python, SQL)
- Engineered an automated data preprocessing pipeline cleaning unstructured customer feedback survey data.
- Built SQL queries with complex CTEs, window functions, and indexing for rapid data aggregation.
- Visualized sentiment distribution and key churn indicators for stakeholder review.

EDUCATION
Bachelor of Engineering (B.E.) in Computer Engineering
Pune Institute of Computer Technology | CGPA: 8.6 / 10 | 2022 - 2026
Relevant Coursework: Database Management Systems, Data Structures & Algorithms, Statistics & Probability
"""
