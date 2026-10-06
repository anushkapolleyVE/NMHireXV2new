"""All actual NM-HireX business functions.

Each function is intentionally small and directly composable; LangGraph is not
required for this deterministic pipeline.
"""
import os
import shutil
import tempfile
import zipfile

import hashlib, json, re, time, logging, os, base64
from pathlib import Path
import gdown
from uuid import UUID
from sqlalchemy import select, delete, text, and_, or_, func, String
from sqlalchemy.orm import Session
from openai import OpenAI
from pypdf import PdfReader
from docx import Document
import pymupdf
from PIL import Image
from .config import settings
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from .models import (
    User,
    Job,
    JobRequirement,
    Candidate,
    Resume,
    CandidateSkill,
    CandidateExperience,
    CandidateEducation,
    CandidateCertification,
    CandidateProject,
    JobCandidate,
    ScreeningResult,
    ScreeningRun,
    AIExtractionLog,
    CandidateContact,
    CandidateSource,
    CandidateAssessment,
    JobSource,
)

OPENAI_API_KEY = settings.OPENAI_API_KEY

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
luna_client = openai_client

OCR_MODEL = "gpt-4o"

# ------------------------------------------------------------
# EXTERNAL RESUME MATCHING API
# ------------------------------------------------------------
# The API key is intentionally read from the server environment/settings only.
# Do NOT expose it to the React/frontend application.
RESUME_MATCHING_BASE_URL = os.getenv(
    "RESUME_MATCHING_BASE_URL",
    getattr(
        settings,
        "RESUME_MATCHING_BASE_URL",
        "https://d4u8k6edt3njs.cloudfront.net/api/public/resume-matching/v1",
    ),
).rstrip("/")

RESUME_MATCHING_API_KEY = os.getenv(
    "RESUME_MATCHING_API_KEY",
    getattr(settings, "RESUME_MATCHING_API_KEY", ""),
)

def _resume_matching_request(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
) -> dict | list:
    """Call the external Résumé Matching API using the server-side x-api-key."""
    if not RESUME_MATCHING_API_KEY:
        raise RuntimeError(
            "RESUME_MATCHING_API_KEY is not configured on the server."
        )

    url = f"{RESUME_MATCHING_BASE_URL}/{path.lstrip('/')}"

    if params:
        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }
        if clean_params:
            url = f"{url}?{urllib.parse.urlencode(clean_params)}"

    headers = {
        "Accept": "application/json",
        "User-Agent": "NM-HireX/1.0",
        "x-api-key": RESUME_MATCHING_API_KEY,
    }

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method.upper(),
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw_response": raw}

    except urllib.error.HTTPError as error:
        try:
            error_body = error.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = str(error)
        raise RuntimeError(
            f"Résumé Matching API returned HTTP {error.code}: {error_body}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not connect to Résumé Matching API: {error}"
        ) from error

def get_resume_matching_requisitions(
    status: str | None = "open",
    department: str | None = None,
    q: str | None = None,
    period: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    sort: str | None = "status",
    limit: int = 50,
    offset: int = 0,
    include: str | None = None,
    end_user: str | None = None,
) -> dict | list:
    """
    API 1: list requisitions from the external Résumé Matching API.

    The external contract uses `q` (not `search`) and uses India-calendar
    periods/dates. `include=details` is supported for the requisition picker
    and does not start a Sheela reading.
    """
    if include == "details":
        limit = min(limit, 20)
    else:
        limit = min(limit, 200)

    limit = max(1, int(limit))
    offset = max(0, int(offset))

    return _resume_matching_request(
        "GET",
        "/requisitions",
        params={
            "status": status,
            "department": department,
            "q": q,
            "period": period,
            "created_from": created_from,
            "created_to": created_to,
            "sort": sort,
            "limit": limit,
            "offset": offset,
            "include": include,
            "end_user": end_user,
        },
    )

def _extract_requisition_items(payload) -> list[dict]:
    """Normalize the external /requisitions response into requisition dictionaries."""
    if payload is None:
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("requisitions", "results", "items", "data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_requisition_items(value)
            if nested:
                return nested

    if any(
        key in payload
        for key in (
            "vereq_number",
            "vereQ",
            "vereq",
            "requisition_number",
            "req_number",
        )
    ):
        return [payload]

    return []

def _requisition_value(item: dict, *keys):
    """Return the first non-empty requisition field."""
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None

def create_job_from_resume_matching_requisition(
    db: Session,
    user_id: UUID,
    vereq_number: str,
    end_user: str | None = None,
) -> Job:
    """
    Create a local NM-HireX Job from API 1's requisition details.

    No local JD extraction or candidate scoring is run. The external API is
    the source of the requisition/JD content for this flow.
    """
    vereq_number = str(vereq_number).strip()
    if not vereq_number:
        raise ValueError("VEREQ number is required")

    # Check if a Job for this vereq_number already exists for this user
    existing_sources = db.scalars(
        select(JobSource)
        .join(Job, Job.id == JobSource.job_id)
        .where(
            Job.created_by == user_id,
            JobSource.source_name == "RESUME_MATCHING"
        )
    ).all()
    
    for source in existing_sources:
        if source.search_criteria and source.search_criteria.get("vereq_number") == vereq_number:
            return db.get(Job, source.job_id)

    payload = get_resume_matching_requisitions(
        status="all",
        q=vereq_number,
        include="details",
        limit=20,
        offset=0,
        end_user=end_user,
    )
    requisitions = _extract_requisition_items(payload)

    selected = None
    target = vereq_number.lower()

    for item in requisitions:
        value = _requisition_value(
            item,
            "label",
            "vereq_number",
            "vereQ",
            "vereq",
            "requisition_number",
            "req_number",
            "number",
            "id",
        )
        if value is not None and str(value).strip().lower() == target:
            selected = item
            break

        # The API accepts the numeric form too: 1187 == VEREQ1187.
        normalized_value = str(value).strip().lower() if value is not None else ""
        normalized_target = target.removeprefix("vereq")
        normalized_value = normalized_value.removeprefix("vereq")
        if normalized_value and normalized_value == normalized_target:
            selected = item
            break

    if selected is None and len(requisitions) == 1:
        selected = requisitions[0]

    if selected is None:
        raise ValueError(
            f"VEREQ {vereq_number} was not found in Resume Matching API requisitions."
        )

    title = _requisition_value(
        selected,
        "title",
        "job_title",
        "requisition_title",
        "role",
        "name",
    ) or f"Requisition {vereq_number}"

    description = _requisition_value(
        selected,
        "description",
        "job_description",
        "jobDescription",
    )
    requirements = _requisition_value(
        selected,
        "requirements",
    )
    responsibilities = _requisition_value(
        selected,
        "responsibilities",
    )

    description_parts = [
        str(value).strip()
        for value in (description, requirements, responsibilities)
        if value
    ]
    combined_description = "\n\n".join(description_parts) or None

    location = _requisition_value(
        selected,
        "location",
        "job_location",
        "city",
    )
    work_mode = _requisition_value(
        selected,
        "work_mode",
        "workMode",
        "mode",
    )

    job = Job(
        created_by=user_id,
        title=str(title)[:255],
        description=combined_description,
        location=str(location)[:255] if location else None,
        work_mode=str(work_mode)[:50] if work_mode else None,
        jd_raw_text=combined_description,
        status="READY",
    )

    db.add(job)
    db.flush()

    # Save the external requisition details so NM-HireX retains the JD source
    # and can reproduce the same external matching flow later.
    job_source = JobSource(
        job_id=job.id,
        source_name="RESUME_MATCHING",
        search_criteria={
            "vereq_number": vereq_number,
            "sort": "sheela",
            "include": "details",
            "requisition": selected,
        },
        status="READY",
        candidates_found=0,
        searched_at=datetime.utcnow(),
    )
    db.add(job_source)

    # Populate the existing structured JD table without asking another model
    # to extract the requisition. The external API already provides the key
    # skills and Sheela checklist.
    checks = selected.get("what_sheela_checks")
    mandatory = []
    preferred = []
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            label = check.get("label") or check.get("short")
            if not label:
                continue
            if check.get("must") is True:
                mandatory.append(str(label))
            else:
                preferred.append(str(label))

    key_skills = selected.get("key_skills")
    if isinstance(key_skills, list):
        for skill in key_skills:
            skill_text = str(skill).strip()
            if skill_text and skill_text not in mandatory and skill_text not in preferred:
                mandatory.append(skill_text)

    try:
        existing_req = db.scalar(
            select(JobRequirement).where(JobRequirement.job_id == job.id)
        )
        if existing_req is None:
            existing_req = JobRequirement(
                job_id=job.id,
                job_title=str(title)[:255],
                minimum_experience=safe_float(
                    selected.get("min_experience_years")
                ),
                location=str(location)[:255] if location else None,
                work_mode=str(work_mode)[:50] if work_mode else None,
                mandatory_skills=mandatory,
                preferred_skills=preferred,
                responsibilities=[responsibilities] if responsibilities else [],
                other_requirements=[requirements] if requirements else [],
                extraction_model="external-resume-matching-v1",
                extraction_version="external-requisition-details",
            )
            db.add(existing_req)
    except Exception:
        logging.exception("Failed to populate JobRequirement from external requisition")

    db.commit()
    db.refresh(job)
    return job

def get_resume_matching_matches(
    vereq_number: str,
    sort: str | None = None,
    top: int = 100,
    detail: str = "full",
    limit: int = 100,
    offset: int = 0,
    list_id: str | None = None,
    source: str = "any",
    hide_in_requisition: bool = False,
    hide_below_minimum: bool = False,
    min_match_pct: int = 0,
    sheela_min_verdict: str | None = None,
    min_sheela_score: int = 0,
    exclude_person_ids: str | None = None,
    q: str | None = None,
    sheela: str = "auto",
    end_user: str | None = None,
) -> dict | list:
    """
    API 2: get matched candidates for one VEREQ.

    `sort=sheela` returns Sheela's order. `sheela=auto` starts/joins the
    reading when the key permits it.
    """
    if not vereq_number or not str(vereq_number).strip():
        raise ValueError("VEREQ number is required")

    top = int(top)
    if top not in {50, 100, 200, 500, 1000}:
        raise ValueError("top must be one of 50, 100, 200, 500, 1000")

    detail = str(detail or "full").lower()
    if detail not in {"full", "summary"}:
        raise ValueError("detail must be full or summary")

    max_limit = 100 if detail == "full" else 200
    limit = max(1, min(int(limit), max_limit))

    encoded_vereq = urllib.parse.quote(str(vereq_number).strip(), safe="")

    return _resume_matching_request(
        "GET",
        f"/requisitions/{encoded_vereq}/matches",
        params={
            "top": top,
            "detail": detail,
            "limit": limit,
            "offset": max(0, int(offset)),
            "list_id": list_id,
            "sort": sort,
            "source": source,
            "hide_in_requisition": str(hide_in_requisition).lower(),
            "hide_below_minimum": str(hide_below_minimum).lower(),
            "min_match_pct": min_match_pct,
            "sheela_min_verdict": sheela_min_verdict,
            "min_sheela_score": min_sheela_score,
            "exclude_person_ids": exclude_person_ids,
            "q": q,
            "sheela": sheela,
            "end_user": end_user,
        },
    )

def _extract_poll_seconds(payload) -> int | None:
    """Find poll_after_seconds in the common response shapes."""
    if not isinstance(payload, dict):
        return None

    for key in ("poll_after_seconds", "pollAfterSeconds"):
        value = payload.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass

    for key in ("data", "result", "meta"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            seconds = _extract_poll_seconds(nested)
            if seconds is not None:
                return seconds

    return None

def _extract_match_items(payload) -> list[dict]:
    """
    Normalize the external API response into a list of candidate dictionaries.

    The API documentation supplied to NM-HireX describes ranked matches but does
    not provide a fixed response example here, so this helper accepts the common
    `matches`, `candidates`, `results`, `items`, `data`, and `result` shapes.
    """
    if payload is None:
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("matches", "candidates", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for key in ("data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_match_items(value)
            if nested:
                return nested

    # A single candidate object can also be returned directly.
    candidate_keys = {
        "name", "full_name", "candidate_name", "email", "phone",
        "resume_url", "resume_link", "resume", "person_id",
        "candidate_id",
        "external_candidate_id", "score", "rank", "ranking",
    }
    if candidate_keys.intersection(payload.keys()):
        return [payload]

    return []

def _candidate_value(item: dict, *keys):
    """Return the first non-empty value from a candidate payload."""
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None

def _resume_text_from_match(item: dict) -> str | None:
    """Extract full résumé text/reading when the external API returns it."""
    value = _candidate_value(
        item,
        "resume_text",
        "full_resume",
        "full_resume_text",
        "resume_reading",
        "full_reading",
        "resume_content",
        "text",
    )
    if isinstance(value, str) and value.strip():
        return value.strip()

    resume = item.get("resume")
    if isinstance(resume, dict):
        value = _candidate_value(
            resume,
            "text",
            "full_text",
            "content",
            "reading",
        )
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None

def _resume_url_from_match(item: dict) -> str | None:
    """Extract the résumé download/profile URL from the external payload."""
    value = _candidate_value(
        item,
        "resume_url",
        "resume_link",
        "resume_download_url",
        "download_url",
        "profile_url",
    )
    if isinstance(value, str):
        return value.strip() or None

    resume = item.get("resume")
    if isinstance(resume, dict):
        value = _candidate_value(
            resume,
            "url",
            "download_url",
            "link",
        )
        if isinstance(value, str):
            return value.strip() or None

    return None

def _external_candidate_id(item: dict, resume_url: str | None) -> str:
    """Create a stable source ID when the API does not return one explicitly."""
    value = _candidate_value(
        item,
        "candidate_id",
        "external_candidate_id",
        "id",
        "profile_id",
        "candidateId",
    )
    if value is not None:
        return str(value)

    email = _candidate_value(item, "email", "email_address")
    if email:
        return str(email).strip().lower()

    phone = _candidate_value(item, "phone", "mobile", "phone_number")
    name = _candidate_value(item, "name", "full_name", "candidate_name")
    stable = f"{name or ''}|{phone or ''}|{resume_url or ''}"
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()

def poll_resume_matching_matches(
    vereq_number: str,
    max_attempts: int | None = None,
    default_wait_seconds: int | None = None,
    top: int = 100,
    end_user: str | None = None,
) -> dict | list:
    """
    Call API 2, wait according to meta.sheela.poll_after_seconds, then call
    again in Sheela order until the reading is complete or the safety limit is
    reached.
    """
    max_attempts = max_attempts or int(
        getattr(settings, "RESUME_MATCHING_POLL_MAX_ATTEMPTS", 6) or 6
    )
    default_wait_seconds = default_wait_seconds or int(
        getattr(settings, "RESUME_MATCHING_POLL_DEFAULT_WAIT_SECONDS", 5) or 5
    )

    first = get_resume_matching_matches(
        vereq_number,
        top=top,
        detail="full",
        limit=min(top, 100),
        sort=None,
        sheela="auto",
        end_user=end_user,
    )

    current = first
    for attempt in range(max_attempts + 1):
        poll_after = _extract_poll_seconds(current)

        if poll_after is None:
            # No active reading remains. Ensure the stored order is Sheela order.
            if attempt == 0 or not _extract_match_items(current):
                return get_resume_matching_matches(
                    vereq_number,
                    sort="sheela",
                    top=top,
                    detail="full",
                    limit=min(top, 100),
                    sheela="auto",
                    end_user=end_user,
                )
            return current

        if attempt >= max_attempts:
            logging.warning(
                "Sheela polling limit reached for VEREQ %s; returning latest response.",
                vereq_number,
            )
            return current

        wait_seconds = max(0, int(poll_after or default_wait_seconds))
        if wait_seconds:
            time.sleep(wait_seconds)

        current = get_resume_matching_matches(
            vereq_number,
            sort="sheela",
            top=top,
            detail="full",
            limit=min(top, 100),
            sheela="auto",
            end_user=end_user,
        )

    return current

def _create_candidate_from_external_match(
    db: Session,
    item: dict,
    source_name: str = "RESUME_MATCHING",
) -> tuple[Candidate, CandidateSource, bool]:
    """Create or update one local Candidate from an external match."""
    resume_url = _resume_url_from_match(item)
    external_id = _external_candidate_id(item, resume_url)

    source = db.scalar(
        select(CandidateSource).where(
            CandidateSource.source_name == source_name,
            CandidateSource.external_candidate_id == external_id,
        )
    )

    candidate = None
    created = False

    if source:
        candidate = db.get(Candidate, source.candidate_id)

    if candidate is None:
        email = _candidate_value(item, "email", "email_address")
        if email:
            candidate = db.scalar(
                select(Candidate).where(
                    func.lower(Candidate.email) == str(email).strip().lower()
                )
            )

    name = _candidate_value(item, "name", "full_name", "candidate_name")
    email = _candidate_value(item, "email", "email_address")
    phone = _candidate_value(item, "phone", "mobile", "phone_number")
    location = _candidate_value(item, "location", "city", "current_location")
    current_company = _candidate_value(
        item,
        "current_company",
        "company",
        "currentCompany",
    )
    current_role = _candidate_value(
        item,
        "current_role",
        "role",
        "designation",
        "currentRole",
    )
    experience = _candidate_value(
        item,
        "total_experience_years",
        "experience_years",
        "experience",
    )
    notice_period = _candidate_value(
        item,
        "notice_period_days",
        "notice_period",
        "noticePeriodDays",
    )
    profile_summary = _candidate_value(
        item,
        "profile_summary",
        "summary",
        "headline",
    )
    resume_text = _resume_text_from_match(item)

    if candidate is None:
        candidate = Candidate(
            name=str(name or external_id)[:255],
            email=str(email)[:255] if email else None,
            phone=str(phone)[:50] if phone else None,
            location=str(location)[:255] if location else None,
            total_experience_years=safe_float(experience),
            current_company=str(current_company)[:255] if current_company else None,
            current_role=str(current_role)[:255] if current_role else None,
            notice_period_days=(
                int(safe_float(notice_period))
                if safe_float(notice_period) is not None
                else None
            ),
            profile_summary=str(profile_summary) if profile_summary else None,
            raw_profile_text=resume_text,
            normalized_profile=item,
        )
        db.add(candidate)
        db.flush()
        created = True
    else:
        # Fill only missing local fields; do not overwrite recruiter/DB data
        # with an incomplete external payload.
        if not candidate.name and name:
            candidate.name = str(name)[:255]
        if not candidate.email and email:
            candidate.email = str(email)[:255]
        if not candidate.phone and phone:
            candidate.phone = str(phone)[:50]
        if not candidate.location and location:
            candidate.location = str(location)[:255]
        if candidate.total_experience_years is None and experience is not None:
            candidate.total_experience_years = safe_float(experience)
        if not candidate.current_company and current_company:
            candidate.current_company = str(current_company)[:255]
        if not candidate.current_role and current_role:
            candidate.current_role = str(current_role)[:255]
        if candidate.notice_period_days is None and notice_period is not None:
            parsed_notice = safe_float(notice_period)
            if parsed_notice is not None:
                candidate.notice_period_days = int(parsed_notice)
        if not candidate.profile_summary and profile_summary:
            candidate.profile_summary = str(profile_summary)
        if resume_text and not candidate.raw_profile_text:
            candidate.raw_profile_text = resume_text
        if not candidate.normalized_profile:
            candidate.normalized_profile = item

    if source is None:
        source = CandidateSource(
            candidate_id=candidate.id,
            source_name=source_name,
            external_candidate_id=external_id,
            profile_url=resume_url,
            raw_source_data=item,
            fetched_at=datetime.utcnow(),
        )
        db.add(source)
    else:
        source.profile_url = resume_url or source.profile_url
        source.raw_source_data = item
        source.fetched_at = datetime.utcnow()
        source.candidate_id = candidate.id

    # Store the external résumé URL/text in the existing Resume table so the
    # current NM-HireX frontend can use the same resume field it already expects.
    if resume_url or resume_text:
        existing_resume = db.scalar(
            select(Resume)
            .where(Resume.candidate_id == candidate.id)
            .order_by(Resume.uploaded_at.desc())
        )

        if existing_resume is None:
            file_name = f"{external_id}.resume"
            if resume_url:
                try:
                    parsed = urllib.parse.urlparse(resume_url)
                    candidate_name = Path(parsed.path).name
                    if candidate_name:
                        file_name = candidate_name[:255]
                except Exception:
                    pass

            db.add(
                Resume(
                    candidate_id=candidate.id,
                    file_name=file_name,
                    file_url=resume_url,
                    file_type=(
                        Path(urllib.parse.urlparse(resume_url).path).suffix
                        .lower()
                        .lstrip(".")
                        if resume_url
                        else None
                    ),
                    file_size=None,
                    file_hash=None,
                    raw_text=resume_text,
                    parsed_data=item,
                    parsing_status="COMPLETED" if resume_text else "PENDING",
                    extraction_status="COMPLETED" if resume_text else "PENDING",
                    extraction_model=(
                        settings.EXTRACTION_MODEL if resume_text else None
                    ),
                    extraction_version="external-resume-matching-v1",
                )
            )
        else:
            if resume_url:
                existing_resume.file_url = resume_url
            if resume_text and not existing_resume.raw_text:
                existing_resume.raw_text = resume_text
                existing_resume.parsed_data = item
                existing_resume.parsing_status = "COMPLETED"

    db.flush()
    return candidate, source, created

def _sheela_data(item: dict) -> dict:
    value = item.get("sheela")
    return value if isinstance(value, dict) else {}

def _external_match_score(item: dict):
    """Return Sheela's 0-100 score. Resume-match score is only a fallback."""
    sheela = _sheela_data(item)
    score = _candidate_value(sheela, "score")
    if score is not None:
        return safe_float(score)

    # Some API states can return a direct score field. Keep it as a fallback.
    direct = _candidate_value(item, "sheela_score", "score")
    if direct is not None:
        return safe_float(direct)

    return None

def _external_rank(item: dict, fallback_rank: int) -> int:
    sheela = _sheela_data(item)
    rank = _candidate_value(sheela, "sheela_rank")
    if rank is not None:
        try:
            return int(rank)
        except (TypeError, ValueError):
            pass

    rank = _candidate_value(item, "rank")
    if rank is not None:
        try:
            return int(rank)
        except (TypeError, ValueError):
            pass

    return fallback_rank

def sync_resume_matching_candidates(
    db: Session,
    job_id: UUID,
    vereq_number: str,
    top_n: int = 100,
    poll: bool = True,
    end_user: str | None = None,
) -> dict:
    """
    Fetch external matches for a VEREQ and attach them to an NM-HireX Job.

    The external Resume Matching API is the source of truth for matching,
    ranking and candidate score. NM-HireX stores that score in
    JobCandidate.overall_score and does not recalculate it here.
    """
    job = db.get(Job, job_id)
    if not job:
        raise ValueError("Job not found")

    vereq_number = str(vereq_number).strip()
    if not vereq_number:
        raise ValueError("VEREQ number is required")

    payload = (
        poll_resume_matching_matches(vereq_number, top=max(100, top_n), end_user=end_user)
        if poll
        else get_resume_matching_matches(
            vereq_number,
            sort="sheela",
            top=max(100, top_n),
            detail="full",
            limit=min(max(100, top_n), 100),
            sheela="auto",
            end_user=end_user,
        )
    )

    matches = _extract_match_items(payload)
    if not matches:
        raise ValueError(
            f"No candidate matches were returned for VEREQ {vereq_number}."
        )

    # Keep the VEREQ in the existing JobSource JSON rather than requiring a new
    # database column/migration just for this integration.
    job_source = db.scalar(
        select(JobSource).where(
            JobSource.job_id == job_id,
            JobSource.source_name == "RESUME_MATCHING",
        ).order_by(JobSource.searched_at.desc())
    )

    if job_source is None:
        job_source = JobSource(
            job_id=job_id,
            source_name="RESUME_MATCHING",
        )
        db.add(job_source)

    job_source.search_criteria = {
        "vereq_number": vereq_number,
        "sort": "sheela",
    }
    job_source.status = "COMPLETED"
    job_source.candidates_found = len(matches)
    job_source.searched_at = datetime.utcnow()

    saved = []
    shortlist_limit = int(getattr(settings, "OUTREACH_TOP_N", 50) or 50)

    for index, item in enumerate(matches[:top_n], start=1):
        try:
            candidate, source, created = _create_candidate_from_external_match(
                db,
                item,
                source_name="RESUME_MATCHING",
            )

            jc = db.scalar(
                select(JobCandidate).where(
                    JobCandidate.job_id == job_id,
                    JobCandidate.candidate_id == candidate.id,
                )
            )

            parsed_score = _external_match_score(item)
            sheela_rank = _external_rank(item, index)

            if jc is None:
                jc = JobCandidate(
                    job_id=job_id,
                    candidate_id=candidate.id,
                    source_id=source.id,
                    eligibility_status="PENDING",
                    recruitment_status="NEW",
                    overall_score=parsed_score,
                    classification="External Match",
                    ranking_position=sheela_rank,
                    is_shortlisted=(sheela_rank <= shortlist_limit),
                )
                db.add(jc)
            else:
                jc.source_id = source.id
                jc.ranking_position = sheela_rank
                jc.overall_score = parsed_score
                jc.classification = "External Match"

                # Preserve the candidate once they have entered the recruitment
                # workflow, even if a later re-sync moves them below rank 50.
                if jc.recruitment_status in {None, ""}:
                    jc.recruitment_status = "NEW"
                jc.is_shortlisted = (
                    jc.is_shortlisted
                    or index <= shortlist_limit
                )

            saved.append({
                "rank": sheela_rank,
                "candidate_id": str(candidate.id),
                "name": candidate.name,
                "email": candidate.email,
                "phone": candidate.phone,
                "resume_url": _resume_url_from_match(item),
                "score": parsed_score,
                "sheela_score": parsed_score,
                "external_candidate_id": source.external_candidate_id,
                "created": created,
                "is_shortlisted": sheela_rank <= shortlist_limit,
            })

        except Exception as error:
            logging.exception(
                "Failed to save external candidate at rank %s for VEREQ %s",
                index,
                vereq_number,
            )
            # Continue saving the remaining candidates.
            continue

    db.commit()

    return {
        "job_id": str(job_id),
        "vereq_number": vereq_number,
        "source": "RESUME_MATCHING",
        "total_matches_returned": len(matches),
        "candidates_saved": len(saved),
        "candidates": saved,
    }
def safe_float(value):
    """
    Convert AI-extracted experience values into a PostgreSQL-safe float.

    Input:
        value -> AI-extracted value such as:
                 5
                 "5"
                 "5 years"
                 "14+"
                 "6-10"
                 "Not provided"
                 None

    Output:
        float or None
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()

    if not text or text in {
        "not provided",
        "not specified",
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "-"
    }:
        return None

    # Handle ranges such as "6-10"
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", text)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        return (low + high) / 2

    # Handle values such as "14+", "5 years", "3.5 years"
    number_match = re.search(r"\d+(?:\.\d+)?", text)

    if number_match:
        return float(number_match.group())

    return None

# ------------------------------------------------------------
# QUERY FUNCTIONS
# ------------------------------------------------------------
def get_job_candidates(
    db: Session,
    job_id: UUID,
    limit: int = 10,
) -> list[dict]:
    """
    Return ranked candidates for a job.

    The external Resume Matching API score stored in JobCandidate.overall_score
    is the primary score. If an older NM-HireX ScreeningResult exists, its
    breakdown is returned for backward compatibility, but it is not required.
    """
    rows = db.execute(
        select(JobCandidate, Candidate)
        .join(
            Candidate,
            Candidate.id == JobCandidate.candidate_id,
        )
        .where(
            JobCandidate.job_id == job_id,
            JobCandidate.is_shortlisted.is_(True),
        )
        .order_by(
            JobCandidate.ranking_position.asc()
        )
    ).all()

    candidate_ids = [
        candidate.id
        for _, candidate in rows[:limit]
    ]

    resumes = {}
    if candidate_ids:
        all_resumes = db.execute(
            select(Resume)
            .where(Resume.candidate_id.in_(candidate_ids))
            .order_by(Resume.uploaded_at.desc())
        ).scalars().all()

        for resume in all_resumes:
            if resume.candidate_id not in resumes:
                resumes[resume.candidate_id] = resume

    # Load old detailed screening records only when they exist.
    screening_map = {}
    jc_ids = [
        jc.id
        for jc, _ in rows[:limit]
    ]

    if jc_ids:
        screenings = db.execute(
            select(ScreeningResult)
            .where(
                ScreeningResult.job_candidate_id.in_(jc_ids)
            )
        ).scalars().all()

        screening_map = {
            screening.job_candidate_id: screening
            for screening in screenings
        }

    results = []

    for jc, candidate in rows[:limit]:
        screening = screening_map.get(jc.id)

        external_score = (
            float(jc.overall_score)
            if jc.overall_score is not None
            else None
        )

        score = (
            external_score
            if external_score is not None
            else (
                float(screening.total_score)
                if screening and screening.total_score is not None
                else 0
            )
        )

        classification = (
            jc.classification
            or (
                screening.classification
                if screening
                else None
            )
            or "External Match"
        )

        score_breakdown = None

        if screening:
            mandatory = float(screening.mandatory_skills_score or 0)
            experience = float(screening.experience_score or 0)
            domain = float(screening.domain_score or 0)
            preferred = float(screening.preferred_skills_score or 0)
            education = float(screening.education_score or 0)
            location = float(screening.location_score or 0)
            availability = float(screening.availability_score or 0)
            other = float(screening.other_requirements_score or 0)

            score_breakdown = {
                "mandatory_skills": {
                    "score": mandatory,
                    "max_score": 30,
                    "percentage": round((mandatory / 30) * 100),
                },
                "experience": {
                    "score": experience,
                    "max_score": 25,
                    "percentage": round((experience / 25) * 100),
                },
                "domain": {
                    "score": domain,
                    "max_score": 15,
                    "percentage": round((domain / 15) * 100),
                },
                "preferred_skills": {
                    "score": preferred,
                    "max_score": 10,
                    "percentage": round((preferred / 10) * 100),
                },
                "education": {
                    "score": education,
                    "max_score": 5,
                    "percentage": round((education / 5) * 100),
                },
                "location": {
                    "score": location,
                    "max_score": 5,
                    "percentage": round((location / 5) * 100),
                },
                "availability": {
                    "score": availability,
                    "max_score": 5,
                    "percentage": round((availability / 5) * 100),
                },
                "other_requirements": {
                    "score": other,
                    "max_score": 5,
                    "percentage": round((other / 5) * 100),
                },
            }
        else:
            score_breakdown = {
                "external_match_score": {
                    "score": score,
                    "max_score": 100,
                    "percentage": score,
                }
            }

        reasoning = None
        if screening and screening.matching_details:
            reasoning = screening.matching_details.get(
                "evaluation"
            )

        resume = resumes.get(candidate.id)

        results.append({
            "rank": jc.ranking_position,
            "candidate_id": str(candidate.id),
            "job_candidate_id": str(jc.id),
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "resume_url": (
                resume.file_url
                if resume
                else None
            ),
            "experience_years": (
                float(candidate.total_experience_years)
                if candidate.total_experience_years is not None
                else None
            ),
            "current_company": candidate.current_company,
            "current_role": candidate.current_role,
            "location": candidate.location,
            "notice_period_days": candidate.notice_period_days,
            "skills": (
                candidate.normalized_profile.get("skills", [])
                if candidate.normalized_profile
                else []
            ),
            "experience_details": (
                candidate.normalized_profile.get("experiences", [])
                if candidate.normalized_profile
                else []
            ),
            "score": score,
            "external_score": external_score,
            "classification": classification,
            "status": jc.recruitment_status,
            "score_breakdown": score_breakdown,
            "reasoning": reasoning,
        })

    return results

def get_user_jobs(db: Session, user_id: UUID) -> list[dict]:
    """Input: authenticated user UUID. Output: only that user's JDs."""
    jobs = db.scalars(select(Job).where(Job.created_by == user_id).order_by(Job.created_at.desc())).all()
    return [{"job_id": str(j.id), "id": str(j.id), "title": j.title, "description": j.description or j.jd_raw_text, "location": j.location, "work_mode": j.work_mode, "file_name": j.jd_file_name, "status": j.status,
             "created_at": j.created_at.isoformat() if j.created_at else None} for j in jobs]

def get_user_job_candidates(db: Session, user_id: UUID, job_id: UUID) -> list[dict]:
    """Input: authenticated user and job UUID. Output: Top 10 only when the user owns the JD."""
    if not db.scalar(select(Job.id).where(Job.id == job_id, Job.created_by == user_id)):
        raise PermissionError("Job does not belong to current user")
    return get_job_candidates(db, job_id)

def get_admin_jobs(db: Session) -> list[dict]:
    """Input: DB session. Output: all JDs with uploader and Top 10 summary."""
    rows = db.execute(select(Job, User).join(User, User.id == Job.created_by).order_by(Job.created_at.desc())).all()
    return [{"job_id": str(j.id), "title": j.title, "file_name": j.jd_file_name, "status": j.status,
             "uploaded_by": {"id": str(u.id), "name": u.name, "email": u.email},
             "top_10": get_job_candidates(db, j.id)} for j, u in rows]

def get_admin_job_candidates(db: Session, job_id: UUID) -> list[dict]:
    """Input: job UUID. Output: Top 10 persisted candidates for that JD."""
    if not db.get(Job, job_id):
        raise ValueError("Job not found")
    return get_job_candidates(db, job_id)

def get_user_dashboard(db: Session, user_id: UUID) -> dict:
    """Input: user UUID. Output: aggregate dashboard stats and pipeline."""
    user = db.get(User, user_id)
    if not user:
        raise ValueError("User not found")
        
    jobs = db.scalars(select(Job).where(Job.created_by == user_id).order_by(Job.created_at.desc())).all()
    active_jobs = len(jobs)
    
    job_ids = [j.id for j in jobs]
    
    # Bulk fetch requirements to avoid N+1 queries
    reqs = {}
    sources_data = {}
    if job_ids:
        job_reqs = db.execute(select(JobRequirement).where(JobRequirement.job_id.in_(job_ids))).scalars().all()
        for r in job_reqs:
            reqs[r.job_id] = r
            
        job_sources = db.execute(
            select(JobSource).where(JobSource.job_id.in_(job_ids), JobSource.source_name == "RESUME_MATCHING")
        ).scalars().all()
        for s in job_sources:
            if s.search_criteria:
                vereq = s.search_criteria.get("vereq_number")
                if vereq:
                    sources_data[s.job_id] = vereq
            
    screened_data = {}
    if job_ids:
        rows = db.execute(
            select(JobCandidate.job_id, JobCandidate.overall_score)
            .where(JobCandidate.job_id.in_(job_ids), JobCandidate.is_shortlisted == True)
        ).all()
        for j_id, score in rows:
            if j_id not in screened_data:
                screened_data[j_id] = {"screened": 0, "strong": 0}
            screened_data[j_id]["screened"] += 1
            if score and float(score) >= 80:
                screened_data[j_id]["strong"] += 1

    total_screened = 0
    strong_matches = 0
    whatsapp_outreach = 0
    
    pipeline = []
    
    for j in jobs:
        s_data = screened_data.get(j.id, {"screened": 0, "strong": 0})
        screened_count = s_data["screened"]
        strong_count = s_data["strong"]
        
        total_screened += screened_count
        strong_matches += strong_count
        
        j_req = reqs.get(j.id)
        exp_str = "N/A"
        if j_req:
            min_exp = j_req.minimum_experience
            max_exp = j_req.maximum_experience
            if min_exp and max_exp: 
                exp_str = f"{int(min_exp)}-{int(max_exp)} yrs"
            elif min_exp: 
                exp_str = f"{int(min_exp)}+ yrs"
                
        pipeline.append({
            "job_id": str(j.id),
            "title": j.title,
            "location": j.location or "Remote",
            "experience": exp_str,
            "sources": "Database",
            "screened": screened_count,
            "strong": strong_count,
            "outreach_count": 0,
            "outreach_total": screened_count,
            "status": j.status,
            "vereq_number": sources_data.get(j.id)
        })
        
    return {
        "user_name": user.name,
        "metrics": {
            "active_jobs": active_jobs,
            "candidates_screened": total_screened,
            "strong_matches": strong_matches,
            "whatsapp_outreach": whatsapp_outreach
        },
        "pipeline": pipeline
    }

def _clean_whatsapp_phone(raw_phone: str | None) -> str:
    """Normalize an Indian WhatsApp number to digits with country code."""
    if not raw_phone:
        return ""

    clean_phone = "".join(
        filter(str.isdigit, str(raw_phone))
    )

    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    return clean_phone

def _whatsapp_headers() -> dict:
    """Build NMVE WhatsApp headers from server-side configuration."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    api_key = getattr(settings, "WHATSAPP_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["api-key"] = api_key

    return headers

def _extract_provider_message_id(response_body: str | dict | None) -> str | None:
    """Extract a provider message ID without assuming one fixed NMVE response shape."""
    if isinstance(response_body, dict):
        for key in (
            "messageId",
            "message_id",
            "externalMessageId",
            "external_message_id",
            "id",
        ):
            value = response_body.get(key)
            if value:
                return str(value)

        for nested_key in ("data", "result", "message"):
            nested = response_body.get(nested_key)
            if isinstance(nested, dict):
                nested_id = _extract_provider_message_id(nested)
                if nested_id:
                    return nested_id

    return None

def _send_whatsapp_payload(payload: dict) -> tuple[bool, dict | None, str | None]:
    """Send a payload to NMVE and return success, parsed response, provider ID."""
    url = getattr(
        settings,
        "WHATSAPP_BASE_URL",
        "https://nmve.io/whatsapp/api/integrations/whatsapp/messages",
    )

    api_key = getattr(settings, "WHATSAPP_API_KEY", "")
    if not api_key:
        print("WHATSAPP_API_KEY is not configured.")
        return False, None, None

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=_whatsapp_headers(),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(
                f"WhatsApp API response status: {response.status}"
            )

            parsed = None
            if body.strip():
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = {"raw_response": body}

            return (
                True,
                parsed,
                _extract_provider_message_id(parsed),
            )

    except urllib.error.HTTPError as http_err:
        try:
            error_body = http_err.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = str(http_err)

        print(
            f"WhatsApp API HTTP Error: {http_err.code}"
        )
        print(
            f"Error Details: {error_body}"
        )
        return False, None, None

    except Exception as error:
        print(
            f"WhatsApp API Error: {error}"
        )
        return False, None, None

def _send_whatsapp_to_candidate(
    db: Session,
    job_id: UUID,
    candidate_id: UUID,
    target_phone: str | None = None,
):
    """
    Send the initial NMVE WhatsApp template to one candidate.

    Phone priority remains:
        target_phone -> WHATSAPP_STAGE_NUMBER -> candidate.phone

    The function records the successful outbound message in candidate_contacts
    and moves a NEW candidate to CONTACTED. No candidate score is calculated here.
    """
    print(
        f"--- Attempting WhatsApp Integration for candidate "
        f"{candidate_id} ---"
    )

    try:
        candidate = db.query(Candidate).filter(
            Candidate.id == candidate_id
        ).first()

        if not candidate:
            print("Candidate not found in DB.")
            return False

        job_candidate = db.scalar(
            select(JobCandidate).where(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == candidate_id,
            )
        )

        if not job_candidate:
            print("JobCandidate not found.")
            return False

        # --------------------------------------------------
        # PHONE NUMBER
        # --------------------------------------------------
        raw_phone = target_phone

        if not raw_phone:
            raw_phone = getattr(
                settings,
                "WHATSAPP_STAGE_NUMBER",
                None,
            )

        if not raw_phone:
            raw_phone = (
                str(candidate.phone)
                if candidate.phone
                else ""
            )

        clean_phone = _clean_whatsapp_phone(raw_phone)

        if not clean_phone:
            print(
                "No valid phone number available for candidate. "
                "Skipping WhatsApp."
            )
            return False

        # --------------------------------------------------
        # CONFIGURATION
        # --------------------------------------------------
        callback_url = getattr(
            settings,
            "WHATSAPP_CALLBACK_URL",
            "https://nmhirex.onrender.com/api/webhooks/whatsapp",
        )

        template_name = getattr(
            settings,
            "WHATSAPP_TEMPLATE_NAME",
            "hello_world",
        )

        template_language = getattr(
            settings,
            "WHATSAPP_TEMPLATE_LANGUAGE",
            "en_US",
        )

        reference_id = (
            f"NMHireX-{str(job_candidate.id)}"
        )

        payload = {
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": template_language,
                },
            },
            "referenceId": reference_id,
            "callbackUrl": callback_url,
        }

        print(
            f"Sending WhatsApp payload to {clean_phone}..."
        )
        success, response_body, provider_message_id = (
            _send_whatsapp_payload(payload)
        )

        if not success:
            return False

        # --------------------------------------------------
        # SAVE OUTBOUND MESSAGE
        # --------------------------------------------------
        contact = CandidateContact(
            job_candidate_id=job_candidate.id,
            channel="WHATSAPP",
            message_type="OUTBOUND",
            message="Hi",
            provider="NMVE",
            external_message_id=provider_message_id,
            status="SENT",
            sent_at=datetime.utcnow(),
        )

        db.add(contact)

        if job_candidate.recruitment_status in {
            None,
            "NEW",
            "SHORTLISTED",
        }:
            job_candidate.recruitment_status = "CONTACTED"

        db.commit()

        print(
            "WhatsApp message saved to candidate_contacts."
        )

        return True

    except Exception as error:
        db.rollback()
        print(
            f"Error in WhatsApp integration: {error}"
        )
        return False

def _send_whatsapp_text_message(
    raw_phone: str,
    text_message: str,
):
    """Send a plain-text WhatsApp message through NMVE."""
    try:
        clean_phone = _clean_whatsapp_phone(raw_phone)

        if not clean_phone:
            print("No valid phone number supplied.")
            return False

        payload = {
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": text_message,
            },
        }

        success, _, _ = _send_whatsapp_payload(payload)

        if success:
            print(
                f"WhatsApp text message sent to {clean_phone}."
            )

        return success

    except Exception as error:
        print(
            f"Error sending WhatsApp text: {error}"
        )
        return False

def _send_whatsapp_cta_message(
    raw_phone: str,
    job_candidate_id: str,
):
    """Send the interview scheduling CTA, with text fallback."""
    clean_phone = _clean_whatsapp_phone(raw_phone)

    if not clean_phone:
        print("No valid phone number supplied.")
        return False

    frontend_url = getattr(
        settings,
        "FRONTEND_URL",
        "http://localhost:5173",
    ).rstrip("/")

    scheduling_link = (
        f"{frontend_url}/schedule/{job_candidate_id}"
    )

    payload = {
        "to": clean_phone,
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "header": {
                "type": "text",
                "text": "Great news! 🎉",
            },
            "body": {
                "text": (
                    "Please schedule your interview at a convenient "
                    "date and time within the next 7 days.\n\n"
                    "Tap the button below to select your preferred "
                    "date and time.\n\n"
                    "We look forward to connecting with you! 😊"
                ),
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Schedule Now",
                    "url": scheduling_link,
                },
            },
        },
    }

    try:
        success, _, _ = _send_whatsapp_payload(payload)

        if success:
            print(
                f"WhatsApp CTA message sent to {clean_phone}."
            )
            return True

    except Exception as error:
        print(
            f"Error sending WhatsApp CTA: {error}"
        )

    # ------------------------------------------------------
    # FALLBACK: PLAIN TEXT SCHEDULING LINK
    # ------------------------------------------------------
    print(
        "Falling back to plain text message with URL..."
    )

    fallback_msg = (
        "Great news! 🎉 We'd love to move forward with "
        "your application.\n\n"
        "Please schedule your interview at a convenient "
        "date and time within the next 7 days.\n\n"
        "Tap the link below to select your preferred "
        "date and time:\n"
        f"👉 {scheduling_link}\n\n"
        "We look forward to connecting with you! 😊"
    )

    return _send_whatsapp_text_message(
        raw_phone,
        fallback_msg,
    )

def _candidate_has_contact_history(
    db: Session,
    job_candidate_id: UUID,
) -> bool:
    """Return True when WhatsApp/email/SMS contact already exists for this requisition."""
    return db.scalar(
        select(CandidateContact.id)
        .where(
            CandidateContact.job_candidate_id == job_candidate_id
        )
        .limit(1)
    ) is not None

def _candidate_has_interview_history(
    db: Session,
    job_candidate_id: UUID,
) -> bool:
    """Use candidate_assessments to detect an existing interview record."""
    return db.scalar(
        select(CandidateAssessment.id)
        .where(
            CandidateAssessment.job_candidate_id == job_candidate_id,
            func.lower(CandidateAssessment.assessment_type).in_(
                [
                    "interview",
                    "interview_scheduled",
                    "interview_link",
                ]
            ),
        )
        .limit(1)
    ) is not None

def get_top_outreach_candidates(
    db: Session,
    job_id: UUID,
    limit: int = 50,
) -> list[dict]:
    """
    Select the externally ranked top candidates for WhatsApp outreach.

    The external rank/score is authoritative. NM-HireX only applies the
    recruitment-history check before sending outreach.
    """
    rows = db.execute(
        select(JobCandidate, Candidate)
        .join(
            Candidate,
            Candidate.id == JobCandidate.candidate_id,
        )
        .where(
            JobCandidate.job_id == job_id,
            JobCandidate.is_shortlisted.is_(True),
            JobCandidate.recruitment_status.in_([
                "NEW",
                "SHORTLISTED",
            ]),
        )
        .order_by(
            JobCandidate.ranking_position.asc()
        )
        .limit(limit)
    ).all()

    eligible = []

    for jc, candidate in rows:
        has_contact = _candidate_has_contact_history(
            db,
            jc.id,
        )
        has_interview = _candidate_has_interview_history(
            db,
            jc.id,
        )

        eligible.append({
            "job_candidate_id": str(jc.id),
            "candidate_id": str(candidate.id),
            "name": candidate.name,
            "phone": candidate.phone,
            "email": candidate.email,
            "rank": jc.ranking_position,
            "score": (
                float(jc.overall_score)
                if jc.overall_score is not None
                else None
            ),
            "has_contact_history": has_contact,
            "has_interview_history": has_interview,
            "eligible_for_outreach": not has_contact and not has_interview,
        })

    return eligible

def send_top_outreach(
    db: Session,
    job_id: UUID,
    limit: int = 50,
) -> dict:
    """Send WhatsApp only to the top externally ranked candidates with no history."""
    candidates = get_top_outreach_candidates(
        db,
        job_id,
        limit=limit,
    )

    results = []

    for item in candidates:
        if not item["eligible_for_outreach"]:
            results.append({
                **item,
                "status": "SKIPPED_HISTORY",
            })
            continue

        if not item["phone"]:
            results.append({
                **item,
                "status": "SKIPPED_NO_PHONE",
            })
            continue

        sent = _send_whatsapp_to_candidate(
            db=db,
            job_id=job_id,
            candidate_id=UUID(item["candidate_id"]),
        )

        results.append({
            **item,
            "status": "SENT" if sent else "FAILED",
        })

    return {
        "job_id": str(job_id),
        "requested_limit": limit,
        "selected": len(candidates),
        "sent": sum(
            1 for item in results
            if item["status"] == "SENT"
        ),
        "skipped_history": sum(
            1 for item in results
            if item["status"] == "SKIPPED_HISTORY"
        ),
        "skipped_no_phone": sum(
            1 for item in results
            if item["status"] == "SKIPPED_NO_PHONE"
        ),
        "failed": sum(
            1 for item in results
            if item["status"] == "FAILED"
        ),
        "results": results,
    }

def _classify_whatsapp_response(message: str) -> str:
    """Simple deterministic YES/NO classifier for recruitment responses."""
    text_value = (message or "").strip().lower()

    negative_patterns = [
        r"\bnot interested\b",
        r"\bno thanks\b",
        r"\bdo not want\b",
        r"\bdon't want\b",
        r"\bdecline\b",
        r"\bnot looking\b",
        r"\bno\b",
    ]

    for pattern in negative_patterns:
        if re.search(pattern, text_value):
            return "NOT_INTERESTED"

    positive_patterns = [
        r"\byes\b",
        r"\binterested\b",
        r"\bsure\b",
        r"\bok\b",
        r"\bokay\b",
        r"\bproceed\b",
        r"\binterview\b",
        r"\bschedule\b",
    ]

    for pattern in positive_patterns:
        if re.search(pattern, text_value):
            return "INTERESTED"

    return "UNKNOWN"

def handle_whatsapp_webhook(
    db: Session,
    payload: dict,
) -> dict:
    """Process an inbound NMVE WhatsApp webhook and advance the recruitment workflow."""

    def find_value(data, keys):
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, (str, int, float)) and str(value).strip():
                    return str(value).strip()
            for nested in data.values():
                result = find_value(nested, keys)
                if result:
                    return result
        elif isinstance(data, list):
            for nested in data:
                result = find_value(nested, keys)
                if result:
                    return result
        return None

    phone = _clean_whatsapp_phone(
        find_value(
            payload,
            ["from", "phone", "sender", "wa_id", "waId", "phoneNumber", "fromNumber"],
        )
    )

    text_message = find_value(
        payload,
        ["text", "body", "messageText", "content"],
    ) or ""

    reference_id = find_value(
        payload,
        ["referenceId", "reference_id", "reference"],
    )

    provider_message_id = find_value(
        payload,
        ["messageId", "message_id", "externalMessageId", "external_message_id", "id"],
    )

    if not phone and not reference_id:
        return {
            "status": "IGNORED",
            "reason": "Missing phone and reference ID",
        }

    # First try the reference ID generated by NM-HireX.
    job_candidate = None
    if reference_id:
        candidate_prefix = "NMHireX-"
        if reference_id.startswith(candidate_prefix):
            candidate_job_id = reference_id[len(candidate_prefix):]
            try:
                job_candidate = db.get(JobCandidate, UUID(candidate_job_id))
            except (ValueError, TypeError):
                job_candidate = None

    # Fall back to the latest active candidate record for the phone number.
    if job_candidate is None and phone:
        job_candidate = db.execute(
            select(JobCandidate)
            .join(Candidate, Candidate.id == JobCandidate.candidate_id)
            .where(
                Candidate.phone == phone,
                JobCandidate.recruitment_status.in_([
                    "CONTACTED",
                    "INTERESTED",
                    "INTERVIEW_LINK_SENT",
                ]),
            )
            .order_by(JobCandidate.updated_at.desc())
        ).scalars().first()

    if not job_candidate:
        return {
            "status": "IGNORED",
            "reason": "No active JobCandidate found",
        }

    if provider_message_id:
        duplicate = db.scalar(
            select(CandidateContact.id)
            .where(CandidateContact.external_message_id == provider_message_id)
            .limit(1)
        )
        if duplicate:
            return {
                "status": "DUPLICATE",
                "job_candidate_id": str(job_candidate.id),
            }

    inbound = CandidateContact(
        job_candidate_id=job_candidate.id,
        channel="WHATSAPP",
        message_type="INBOUND",
        message=text_message,
        response_text=text_message,
        provider="NMVE",
        external_message_id=provider_message_id,
        status="REPLIED",
        responded_at=datetime.utcnow(),
    )
    db.add(inbound)
    db.commit()

    intent = _classify_whatsapp_response(text_message)
    inbound.response_intent = intent
    db.commit()

    if intent == "INTERESTED":
        job_candidate.recruitment_status = "INTERESTED"
        db.commit()

        sent = _send_whatsapp_cta_message(
            raw_phone=job_candidate.candidate.phone,
            job_candidate_id=str(job_candidate.id),
        )

        if sent:
            job_candidate.recruitment_status = "INTERVIEW_LINK_SENT"
            db.add(
                CandidateContact(
                    job_candidate_id=job_candidate.id,
                    channel="WHATSAPP",
                    message_type="OUTBOUND",
                    message="Interview scheduling link sent",
                    provider="NMVE",
                    status="SENT",
                    sent_at=datetime.utcnow(),
                )
            )
            db.commit()

    elif intent == "NOT_INTERESTED":
        job_candidate.recruitment_status = "NOT_INTERESTED"
        db.commit()

    else:
        clarification = (
            "Thank you for your response. Please reply YES if you are interested "
            "in proceeding with the opportunity, or NO if you are not interested."
        )
        sent = _send_whatsapp_text_message(
            raw_phone=job_candidate.candidate.phone,
            text_message=clarification,
        )
        db.add(
            CandidateContact(
                job_candidate_id=job_candidate.id,
                channel="WHATSAPP",
                message_type="OUTBOUND",
                message=clarification,
                provider="NMVE",
                status="SENT" if sent else "FAILED",
                sent_at=datetime.utcnow() if sent else None,
            )
        )
        db.commit()

    return {
        "status": intent,
        "job_candidate_id": str(job_candidate.id),
        "candidate_id": str(job_candidate.candidate_id),
        "candidate_name": job_candidate.candidate.name,
        "message": text_message,
    }

def schedule_candidate_interview(
    db: Session,
    job_candidate_id: UUID,
    scheduled_at: datetime,
    interview_link: str | None = None,
) -> dict:
    """Persist the selected interview slot and send the confirmation by WhatsApp."""
    job_candidate = db.get(JobCandidate, job_candidate_id)
    if not job_candidate:
        raise ValueError("JobCandidate not found")

    if job_candidate.recruitment_status == "NOT_INTERESTED":
        raise ValueError("Candidate is not interested")

    job_candidate.interview_scheduled_at = scheduled_at
    job_candidate.interview_link = interview_link
    job_candidate.recruitment_status = "INTERVIEW_SCHEDULED"
    db.commit()

    date_text = scheduled_at.strftime("%d %b %Y, %I:%M %p")
    message = (
        "Your interview has been scheduled successfully! 🎉\n\n"
        f"Date & Time: {date_text}\n"
    )
    if interview_link:
        message += f"\nInterview Link:\n{interview_link}\n"
    message += "\nPlease be available a few minutes before the scheduled time."

    sent = _send_whatsapp_text_message(
        raw_phone=job_candidate.candidate.phone,
        text_message=message,
    )

    db.add(
        CandidateContact(
            job_candidate_id=job_candidate.id,
            channel="WHATSAPP",
            message_type="OUTBOUND",
            message=message,
            provider="NMVE",
            status="SENT" if sent else "FAILED",
            sent_at=datetime.utcnow() if sent else None,
        )
    )
    db.commit()

    return {
        "job_candidate_id": str(job_candidate.id),
        "candidate_id": str(job_candidate.candidate_id),
        "scheduled_at": scheduled_at.isoformat(),
        "interview_link": interview_link,
        "status": job_candidate.recruitment_status,
        "confirmation_sent": sent,
    }

def update_interview_status(
    db: Session,
    job_candidate_id: UUID,
    status: str,
) -> dict:
    """Update interview status without recalculating candidate score."""
    job_candidate = db.get(JobCandidate, job_candidate_id)
    if not job_candidate:
        raise ValueError("JobCandidate not found")

    normalized = status.strip().upper()
    mapping = {
        "SCHEDULED": "INTERVIEW_SCHEDULED",
        "COMPLETED": "INTERVIEW_COMPLETED",
        "NO_SHOW": "INTERVIEW_NO_SHOW",
        "CANCELLED": "INTERVIEW_CANCELLED",
        "REJECTED": "REJECTED",
    }

    if normalized not in mapping:
        raise ValueError(
            "Invalid interview status. Use SCHEDULED, COMPLETED, NO_SHOW, CANCELLED or REJECTED."
        )

    job_candidate.recruitment_status = mapping[normalized]
    db.commit()

    return {
        "job_candidate_id": str(job_candidate.id),
        "candidate_id": str(job_candidate.candidate_id),
        "status": job_candidate.recruitment_status,
        "interview_scheduled_at": (
            job_candidate.interview_scheduled_at.isoformat()
            if job_candidate.interview_scheduled_at
            else None
        ),
        "interview_link": job_candidate.interview_link,
    }

def get_outreach_candidates(
    db: Session,
    user_id: UUID,
) -> list[dict]:
    """Return candidates currently in the WhatsApp recruitment pipeline."""
    rows = db.execute(
        select(JobCandidate, Job, Candidate)
        .join(Job, Job.id == JobCandidate.job_id)
        .join(Candidate, Candidate.id == JobCandidate.candidate_id)
        .where(
            JobCandidate.recruitment_status.in_([
                "CONTACTED",
                "INTERESTED",
                "NOT_INTERESTED",
                "INTERVIEW_LINK_SENT",
            ])
        )
        .order_by(
            JobCandidate.updated_at.desc()
        )
    ).all()

    results = []

    for jc, job, candidate in rows:
        latest_response = db.execute(
            select(CandidateContact)
            .where(
                CandidateContact.job_candidate_id == jc.id,
                CandidateContact.channel == "WHATSAPP",
                CandidateContact.message_type == "INBOUND",
            )
            .order_by(
                CandidateContact.created_at.desc()
            )
        ).scalars().first()

        response_text = (
            latest_response.response_text
            if latest_response
            else None
        )

        response_intent = (
            _classify_whatsapp_response(response_text)
            if response_text
            else None
        )

        responded_at = (
            latest_response.responded_at
            if latest_response
            else None
        )

        results.append({
            "id": str(candidate.id),
            "job_id": str(job.id),
            "job_candidate_id": str(jc.id),
            "name": candidate.name or "Unnamed Candidate",
            "job": job.title or "Unknown Role",
            "status": jc.recruitment_status,
            "score": (
                float(jc.overall_score)
                if jc.overall_score is not None
                else None
            ),
            "rank": jc.ranking_position,
            "response_text": response_text,
            "response_intent": response_intent,
            "responded_at": (
                responded_at.isoformat()
                if responded_at
                else None
            ),
        })

    return results

def update_candidate_status(
    db: Session,
    job_id: UUID,
    candidate_id: UUID,
    status: str,
    target_phone: str | None = None,
):
    """Update recruitment status and trigger initial WhatsApp when appropriate."""
    job_candidate = db.scalar(
        select(JobCandidate).where(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
    )

    if not job_candidate:
        raise ValueError("JobCandidate not found")

    old_status = job_candidate.recruitment_status
    job_candidate.recruitment_status = status.upper()
    db.commit()

    if status.upper() == "CONTACTED" and old_status != "CONTACTED":
        _send_whatsapp_to_candidate(
            db,
            job_id,
            candidate_id,
            target_phone,
        )

    return {
        "job_candidate_id": str(job_candidate.id),
        "candidate_id": str(candidate_id),
        "old_status": old_status,
        "status": job_candidate.recruitment_status,
    }

def get_all_candidates(db: Session, user_id: UUID) -> list[dict]:
    """Return unique candidates currently in the recruitment workflow."""
    rows = db.execute(
        select(Candidate, JobCandidate, Job)
        .join(
            JobCandidate,
            JobCandidate.candidate_id == Candidate.id,
        )
        .join(
            Job,
            Job.id == JobCandidate.job_id,
        )
        .where(
            JobCandidate.recruitment_status.in_([
                "INTERESTED",
                "INTERVIEW_LINK_SENT",
                "INTERVIEW",
                "INTERVIEW_SCHEDULED",
                "INTERVIEW_COMPLETED",
            ])
        )
        .order_by(
            Candidate.created_at.desc(),
            JobCandidate.created_at.desc(),
        )
    ).all()

    seen = set()
    results = []

    for candidate, jc, job in rows:
        if candidate.id in seen:
            continue
        seen.add(candidate.id)

        score = (
            float(jc.overall_score)
            if jc.overall_score is not None
            else 0
        )

        classification = (
            jc.classification
            or "External Match"
        )

        outbound_interview = (
            db.query(CandidateContact)
            .filter(
                CandidateContact.job_candidate_id == jc.id,
                CandidateContact.channel == "WHATSAPP",
                CandidateContact.message_type == "OUTBOUND",
                CandidateContact.message.contains(
                    "http"
                ),
            )
            .order_by(
                CandidateContact.created_at.desc()
            )
            .first()
        )

        interview_link = None
        if outbound_interview and outbound_interview.message:
            urls = re.findall(
                r"https?://\S+",
                outbound_interview.message,
            )
            if urls:
                interview_link = urls[0].rstrip(
                    "!.,)"
                )

        results.append({
            "id": str(candidate.id),
            "job_id": str(job.id),
            "job_candidate_id": str(jc.id),
            "name": candidate.name or "Unnamed",
            "email": candidate.email,
            "phone": candidate.phone,
            "location": candidate.location or "-",
            "exp": (
                f"{candidate.total_experience_years} yrs"
                if candidate.total_experience_years
                else "-"
            ),
            "score": score,
            "scoreLabel": classification,
            "job": job.title,
            "skills": (
                ", ".join(
                    [
                        (
                            item.get("name")
                            or item.get("skill")
                            or item.get("skill_name")
                            or str(item)
                        )
                        if isinstance(item, dict)
                        else str(item)
                        for item in (
                            candidate.normalized_profile.get(
                                "skills", []
                            )
                            if candidate.normalized_profile
                            else []
                        )[:5]
                    ]
                )
                or "-"
            ),
            "stage": jc.recruitment_status,
            "interview_link": interview_link,
            "interview_scheduled_at": None,
            "experience_details": (
                candidate.normalized_profile.get(
                    "experiences", []
                )
                if candidate.normalized_profile
                else []
            ),
            "all_skills": (
                candidate.normalized_profile.get(
                    "skills", []
                )
                if candidate.normalized_profile
                else []
            ),
        })

    return results
