"""
Unit and integration tests for AI Resume Analyzer.
"""
import io
import pytest
from app.resume_analyzer import (
    DEFAULT_SAMPLE_RESUME_TEXT,
    analyze_resume_text,
    compute_skill_gaps,
    extract_skills_from_text,
    generate_pdf_report,
)
import pypdf


def test_extract_skills_from_text():
    """Verify extraction of core skills from sample text."""
    sample = "Proficient in Python, SQL, and Power BI with experience in Data Analysis."
    skills = extract_skills_from_text(sample)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Power BI" in skills
    assert "Data Analysis" in skills


def test_missing_skills_identification():
    """Missing skills should identify benchmark tools like Excel, Tableau for Data Analyst."""
    skills = ["Python", "SQL", "Power BI", "Data Analysis"]
    missing = compute_skill_gaps(skills, "Data Analyst")
    assert "Excel" in missing
    assert "Tableau" in missing


def test_analyze_resume_text_structure():
    """Verify full analysis dictionary contains all required fields and ratings."""
    result = analyze_resume_text(DEFAULT_SAMPLE_RESUME_TEXT, "test_resume.pdf")

    assert "overall_score" in result
    assert 0 <= result["overall_score"] <= 100
    assert "ats_score" in result
    assert 0 <= result["ats_score"] <= 100
    assert result["strength"] in ("Excellent", "Good", "Average", "Needs Improvement")

    # Verify breakdown
    breakdown = result["breakdown"]
    assert "technical_skills_score" in breakdown
    assert "projects_score" in breakdown
    assert "education_score" in breakdown
    assert "experience_score" in breakdown
    assert "ats_score" in breakdown

    # Verify recommendations & suggestions
    assert len(result["skills_found"]) > 0
    assert len(result["missing_skills"]) > 0
    assert len(result["suggestions"]) > 0
    assert len(result["strengths"]) > 0
    assert len(result["weaknesses"]) > 0
    assert len(result["recommendation"]) > 0


def test_generate_pdf_report():
    """Verify PDF generator produces valid PDF bytes with header."""
    result = analyze_resume_text(DEFAULT_SAMPLE_RESUME_TEXT, "aditya.pdf")
    pdf_bytes = generate_pdf_report(result)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")


def test_sample_analysis_endpoint(client):
    """Test GET /analyzer/sample-analysis returns complete scorecard JSON."""
    resp = client.get("/analyzer/sample-analysis")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_score" in data
    assert "skills_found" in data
    assert "missing_skills" in data
    assert "breakdown" in data
    assert "suggestions" in data
    assert "recommendation" in data
    assert "id" in data


def test_upload_and_analyze_endpoint(client):
    """Test POST /analyzer/upload-and-analyze with a generated in-memory PDF."""
    # Create simple in-memory PDF
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    pdf_stream = io.BytesIO()
    writer.write(pdf_stream)
    pdf_stream.seek(0)

    files = {"file": ("my_resume.pdf", pdf_stream.getvalue(), "application/pdf")}
    resp = client.post("/analyzer/upload-and-analyze", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "my_resume.pdf"
    assert "overall_score" in data
    assert "ats_score" in data


def test_upload_invalid_file_rejected(client):
    """Uploading non-PDF file returns 400 Bad Request."""
    files = {"file": ("notes.txt", b"plain text", "text/plain")}
    resp = client.post("/analyzer/upload-and-analyze", files=files)
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_download_report_pdf(client):
    """Test downloading the generated PDF report."""
    # Create an analysis first
    sample_resp = client.get("/analyzer/sample-analysis")
    analysis_id = sample_resp.json()["id"]

    resp = client.get(f"/analyzer/report/{analysis_id}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "AI_Resume_Report" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
