# -*- coding: utf-8 -*-
"""Conservative extraction of public facts from ATS job posts.

Raw descriptions are processed in memory and never returned by this module.
Every extracted field is either explicit in the source or left unknown.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


MAX_DESCRIPTION_CHARS = 250_000

COUNTRY_ALIASES = (
    ("CN", ("china", "mainland china", "prc")),
    ("US", ("united states of america", "united states", "u s a", "usa", "u s", "us")),
    ("GB", ("united kingdom", "great britain", "u k", "uk")),
    ("CA", ("canada",)),
    ("AU", ("australia",)),
    ("NZ", ("new zealand",)),
    ("SG", ("singapore",)),
    ("JP", ("japan",)),
    ("KR", ("south korea", "republic of korea", "korea")),
    ("IN", ("india",)),
    ("DE", ("germany",)),
    ("FR", ("france",)),
    ("IE", ("ireland",)),
    ("IT", ("italy",)),
    ("ES", ("spain",)),
    ("NL", ("netherlands",)),
    ("SE", ("sweden",)),
    ("NO", ("norway",)),
    ("DK", ("denmark",)),
    ("FI", ("finland",)),
    ("BE", ("belgium",)),
    ("LU", ("luxembourg",)),
    ("CH", ("switzerland",)),
    ("AT", ("austria",)),
    ("PL", ("poland",)),
    ("PT", ("portugal",)),
    ("GR", ("greece",)),
    ("AE", ("united arab emirates", "u a e", "uae")),
    ("SA", ("saudi arabia", "ksa")),
    ("IL", ("israel",)),
    ("BR", ("brazil",)),
    ("MX", ("mexico",)),
)

REGION_ALIASES = (
    ("APAC", ("apac", "asia pacific")),
    ("EMEA", ("emea",)),
    ("LATAM", ("latam", "latin america")),
    ("North America", ("north america",)),
    ("Europe", ("europe", "european union", "eu")),
    ("Asia", ("asia",)),
    ("MENA", ("mena", "middle east and north africa")),
    ("DACH", ("dach",)),
    ("Nordics", ("nordics", "nordic countries")),
    ("Balkans", ("balkans",)),
)

CITY_HINTS = (
    ("Beijing", "Beijing", "CN", ("beijing", "北京")),
    ("Shanghai", "Shanghai", "CN", ("shanghai", "上海")),
    ("Shenzhen", "Guangdong", "CN", ("shenzhen", "深圳")),
    ("Guangzhou", "Guangdong", "CN", ("guangzhou", "广州")),
    ("Chengdu", "Sichuan", "CN", ("chengdu", "成都")),
    ("Hangzhou", "Zhejiang", "CN", ("hangzhou", "杭州")),
    ("Suzhou", "Jiangsu", "CN", ("suzhou", "苏州")),
    ("Tianjin", "Tianjin", "CN", ("tianjin", "天津")),
    ("Singapore", None, "SG", ("singapore",)),
    ("Tokyo", "Tokyo", "JP", ("tokyo", "東京")),
    ("Seoul", "Seoul", "KR", ("seoul", "서울")),
    ("Sydney", "New South Wales", "AU", ("sydney",)),
    ("Melbourne", "Victoria", "AU", ("melbourne",)),
    ("London", "England", "GB", ("london",)),
    ("New York", "New York", "US", ("new york",)),
    ("San Francisco", "California", "US", ("san francisco",)),
)

PREFERRED_MARKERS = re.compile(
    r"\b(preferred|ideally|nice to have|bonus|would be a plus|plus if)\b",
    re.IGNORECASE,
)
EXPERIENCE_RANGE_BEFORE = re.compile(
    r"(?P<min>\d{1,2})\s*(?:-|to)\s*(?P<max>\d{1,2})\+?"
    r"\s+years?(?:\s+of)?\b.{0,100}?\bexperience\b",
    re.IGNORECASE,
)
EXPERIENCE_RANGE_AFTER = re.compile(
    r"\bexperience\b.{0,100}?(?P<min>\d{1,2})\s*(?:-|to)\s*"
    r"(?P<max>\d{1,2})\+?\s+years?\b",
    re.IGNORECASE,
)
EXPERIENCE_SINGLE_BEFORE = re.compile(
    r"(?P<min>\d{1,2})\s*\+?\s+years?(?:\s+of)?\b"
    r".{0,100}?\bexperience\b",
    re.IGNORECASE,
)
EXPERIENCE_SINGLE_AFTER = re.compile(
    r"\bexperience\b.{0,80}?\b(?P<min>\d{1,2})\s*\+?\s+years?\b",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    BREAK_TAGS = {
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "section",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def html_to_text(value):
    """Convert bounded Greenhouse HTML to plain text for in-memory parsing."""

    if not isinstance(value, str) or not value:
        return ""
    source = value[:MAX_DESCRIPTION_CHARS]
    for _ in range(2):
        decoded = html.unescape(source)
        if decoded == source:
            break
        source = decoded
    parser = _TextExtractor()
    parser.feed(source)
    parser.close()
    decoded = html.unescape("".join(parser.parts))
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in decoded.replace("\r", "\n").split("\n")
    ]
    return "\n".join(line for line in lines if line)


def _normalized_words(value):
    return " " + re.sub(r"[^a-z0-9]+", " ", value.lower()).strip() + " "


def _has_phrase(words, phrase):
    normalized = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
    return bool(normalized) and f" {normalized} " in words


def extract_country_codes(value):
    words = _normalized_words(value or "")
    result = []
    for code, aliases in COUNTRY_ALIASES:
        if any(_has_phrase(words, alias) for alias in aliases):
            result.append(code)
    return result


def extract_regions(value):
    words = _normalized_words(value or "")
    result = []
    for region, aliases in REGION_ALIASES:
        if any(_has_phrase(words, alias) for alias in aliases):
            result.append(region)
    return result


def parse_places(raw_location):
    raw_location = str(raw_location or "").strip()
    lowered = raw_location.lower()
    places = []
    used_countries = set()
    for city, region, country_code, aliases in CITY_HINTS:
        if any(alias.lower() in lowered for alias in aliases):
            places.append(
                {
                    "city": city,
                    "region": region,
                    "country_code": country_code,
                }
            )
            used_countries.add(country_code)
    for country_code in extract_country_codes(raw_location):
        if country_code not in used_countries:
            places.append(
                {
                    "city": None,
                    "region": None,
                    "country_code": country_code,
                }
            )
    return places[:20]


def _segments(text):
    normalized = text.replace("–", "-").replace("—", "-")
    return [
        segment.strip()
        for segment in re.split(r"[\n\r]+|(?<=[.!?])\s+", normalized)
        if segment.strip()
    ]


def infer_experience(text):
    """Return an explicit required experience range or unknown.

    Preferred/nice-to-have statements are deliberately ignored.
    """

    candidates = []
    for segment in _segments(text):
        if "experience" not in segment.lower() or PREFERRED_MARKERS.search(segment):
            continue
        match = (
            EXPERIENCE_RANGE_BEFORE.search(segment)
            or EXPERIENCE_RANGE_AFTER.search(segment)
        )
        if match:
            minimum = int(match.group("min"))
            maximum = int(match.group("max"))
        else:
            match = (
                EXPERIENCE_SINGLE_BEFORE.search(segment)
                or EXPERIENCE_SINGLE_AFTER.search(segment)
            )
            if not match:
                continue
            minimum = int(match.group("min"))
            maximum = None
        if minimum > 60 or (maximum is not None and maximum > 60):
            continue
        if maximum is not None and minimum > maximum:
            continue
        candidates.append((minimum, maximum))

    if not candidates:
        return {
            "min_years": None,
            "max_years": None,
            "explicit": False,
        }
    minimum, maximum = max(
        candidates,
        key=lambda item: (item[0], item[1] if item[1] is not None else -1),
    )
    return {
        "min_years": minimum,
        "max_years": maximum,
        "explicit": True,
    }


def infer_people_management(text):
    required_patterns = (
        r"\bdirect reports?\b",
        r"\bpeople manager\b",
        r"\bmanag(?:e|es|ed|ement|ing)\s+(?:a|the|our)\s+team\s+of\s+\d+",
        r"\bresponsible for (?:hiring|managing|coaching|developing) "
        r"(?:employees|people|direct reports)\b",
    )
    for segment in _segments(text):
        if PREFERRED_MARKERS.search(segment):
            continue
        if any(re.search(pattern, segment, re.IGNORECASE) for pattern in required_patterns):
            return "required"
    return "unknown"


def infer_portfolio(text):
    portfolio_segments = [
        segment for segment in _segments(text) if "portfolio" in segment.lower()
    ]
    if not portfolio_segments:
        return "not_mentioned"
    for segment in portfolio_segments:
        if PREFERRED_MARKERS.search(segment):
            return "preferred"
    required = re.compile(
        r"\b(required|must|submit|provide|include|upload|link to|share)\b",
        re.IGNORECASE,
    )
    if any(required.search(segment) for segment in portfolio_segments):
        return "required"
    return "unknown"


def infer_people_seniority(title):
    title = str(title or "").lower()
    if re.search(
        r"\b(director|manager|head|vp|vice president|chief)\b", title
    ):
        return "leadership"
    if re.search(r"\b(senior|sr|staff|principal|lead)\b", title):
        return "senior"
    if re.search(r"\b(junior|jr|associate|coordinator|trainee)\b", title):
        return "junior"
    if re.search(
        r"\b(intern|internship|new grad|graduate|campus|entry[- ]level)\b",
        title,
    ):
        return "entry"
    return "unknown"


def infer_work_arrangement(raw_location, text):
    location = str(raw_location or "")
    location_lower = location.lower()
    if "remote" in location_lower:
        return "remote"
    if "hybrid" in location_lower:
        return "hybrid"
    if re.search(r"\bon[- ]?site\b", location, re.IGNORECASE):
        return "onsite"
    if re.search(
        r"\b(this|the)\s+(role|position)\s+is\s+(fully\s+)?remote\b"
        r"|\bfully remote (role|position)\b",
        text,
        re.IGNORECASE,
    ):
        return "remote"
    if re.search(
        r"\b(this|the)\s+(role|position)\s+is\s+hybrid\b"
        r"|\bhybrid (role|position)\b",
        text,
        re.IGNORECASE,
    ):
        return "hybrid"
    if re.search(
        r"\b(this|the)\s+(role|position)\s+is\s+on[- ]?site\b"
        r"|\bon[- ]?site (role|position)\b",
        text,
        re.IGNORECASE,
    ):
        return "onsite"
    return "unknown"


REMOTE_SCOPE_MARKERS = re.compile(
    r"\b("
    r"(?:must|required to|need to)\s+(?:be\s+)?"
    r"(?:currently\s+)?"
    r"(?:based|located|residing)\s+in"
    r"|valid\s+(?:work(?:ing)?\s+)?(?:rights|authorization)\s+to\s+work\s+in"
    r"|remote\s+(?:within|in|from)"
    r"|open\s+to\s+candidates\s+(?:based|located|residing)\s+in"
    r"|only\s+(?:hire|hiring|available|considering|eligible)\b"
    r")",
    re.IGNORECASE,
)


def infer_remote_eligibility(raw_location, text, work_arrangement):
    if work_arrangement != "remote":
        return {
            "scope": "not_applicable",
            "allowed_countries": [],
            "allowed_regions": [],
        }
    combined = f"{raw_location}\n{text}"
    if re.search(
        r"\b(remote worldwide|work from anywhere|any country|globally remote)\b",
        combined,
        re.IGNORECASE,
    ):
        return {
            "scope": "worldwide",
            "allowed_countries": [],
            "allowed_regions": [],
        }
    scope_segments = [
        segment
        for segment in _segments(text)
        if REMOTE_SCOPE_MARKERS.search(segment)
    ]
    scope_text = "\n".join(scope_segments)
    countries = extract_country_codes(scope_text)
    regions = extract_regions(scope_text)
    return {
        "scope": "limited" if countries or regions else "unknown",
        "allowed_countries": countries,
        "allowed_regions": regions,
    }


def _metadata_text(metadata, names):
    names = {name.lower() for name in names}
    if not isinstance(metadata, list):
        return ""
    for item in metadata:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip().lower() not in names:
            continue
        value = item.get("value")
        if isinstance(value, list):
            return " ".join(str(part) for part in value)
        return str(value or "")
    return ""


def infer_employment_type(title, metadata):
    value = " ".join(
        [
            str(title or ""),
            _metadata_text(
                metadata,
                {"employment type", "job type", "employment"},
            ),
        ]
    ).lower()
    if re.search(r"\b(intern|internship)\b", value):
        return "internship"
    if re.search(r"\bpart[- ]time\b", value):
        return "part_time"
    if re.search(r"\b(contract|contractor|fixed[- ]term)\b", value):
        return "contract"
    if re.search(r"\btemporary\b", value):
        return "temporary"
    if re.search(r"\bfreelance\b", value):
        return "freelance"
    if re.search(r"\bfull[- ]time\b", value):
        return "full_time"
    return "unknown"


def _safe_https_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return value


def _iso_date(value):
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value.strip())
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def _evidence(field, summary, source_url, observed_at):
    return {
        "field": field,
        "summary": summary,
        "source_url": source_url,
        "observed_at": observed_at,
    }


def _record_id_part(value):
    normalized = str(value).strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,99}", normalized):
        return normalized
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def _build_public_job(
    company,
    *,
    platform,
    source_job_id,
    title,
    raw_location,
    source_url,
    description_html,
    metadata,
    first_published,
    first_seen_on,
    observed_at,
    work_arrangement_override=None,
    employment_type_override=None,
    country_code_overrides=None,
):
    """Build a schema-v1 record from source-specific public fields."""

    if not isinstance(company, dict):
        return None
    company_id = str(company.get("id") or "").strip().lower()
    company_name = str(company.get("name") or "").strip()
    source_job_id = str(source_job_id or "").strip()
    title = str(title or "").strip()
    raw_location = str(raw_location or "").strip()
    source_url = _safe_https_url(source_url)
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", company_id)
        or not company_name
        or not source_job_id
        or len(source_job_id) > 200
        or not title
        or len(title) > 300
        or not source_url
        or platform not in {
            "greenhouse",
            "smartrecruiters",
            "workday",
        }
    ):
        return None

    text = html_to_text(description_html)
    work_arrangement = (
        work_arrangement_override
        if work_arrangement_override
        in {"onsite", "hybrid", "remote", "unknown"}
        else infer_work_arrangement(raw_location, text)
    )
    location_countries = [
        code
        for code in (country_code_overrides or [])
        if isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", code)
    ]
    remote_eligibility = infer_remote_eligibility(
        raw_location,
        text,
        work_arrangement,
    )
    experience = infer_experience(text)
    people_management = infer_people_management(text)
    portfolio = infer_portfolio(text)
    employment_type = (
        employment_type_override
        if employment_type_override
        in {
            "full_time",
            "part_time",
            "contract",
            "temporary",
            "internship",
            "freelance",
            "unknown",
        }
        else infer_employment_type(title, metadata)
    )
    seniority = infer_people_seniority(title)
    places = parse_places(raw_location)
    place_countries = {
        place["country_code"]
        for place in places
        if place["country_code"] is not None
    }
    for country_code in location_countries:
        if country_code not in place_countries and len(places) < 20:
            places.append(
                {
                    "city": None,
                    "region": None,
                    "country_code": country_code,
                }
            )
            place_countries.add(country_code)

    evidence = []
    if raw_location:
        evidence.append(
            _evidence(
                "location",
                f"The public posting lists {raw_location[:180]} as its location.",
                source_url,
                observed_at,
            )
        )
    if work_arrangement != "unknown":
        article = "an" if work_arrangement == "onsite" else "a"
        evidence.append(
            _evidence(
                "work_arrangement",
                "The public posting explicitly signals "
                f"{article} {work_arrangement} arrangement.",
                source_url,
                observed_at,
            )
        )
    if remote_eligibility["scope"] == "worldwide":
        evidence.append(
            _evidence(
                "remote_eligibility",
                "The public posting explicitly describes worldwide remote eligibility.",
                source_url,
                observed_at,
            )
        )
    elif remote_eligibility["scope"] == "limited":
        scope_parts = (
            remote_eligibility["allowed_countries"]
            + remote_eligibility["allowed_regions"]
        )
        evidence.append(
            _evidence(
                "remote_eligibility",
                "The posting explicitly limits remote eligibility to: "
                + ", ".join(scope_parts)
                + ".",
                source_url,
                observed_at,
            )
        )
    if experience["explicit"]:
        if experience["max_years"] is None:
            experience_summary = (
                "The posting explicitly states a minimum of "
                f"{experience['min_years']} years of experience."
            )
        else:
            experience_summary = (
                "The posting explicitly states an experience range of "
                f"{experience['min_years']}–{experience['max_years']} years."
            )
        evidence.append(
            _evidence(
                "experience",
                experience_summary,
                source_url,
                observed_at,
            )
        )
    if people_management == "required":
        evidence.append(
            _evidence(
                "classification.people_management",
                "The posting explicitly requires responsibility for direct reports or people management.",
                source_url,
                observed_at,
            )
        )
    if portfolio in {"required", "preferred"}:
        evidence.append(
            _evidence(
                "requirements.portfolio",
                f"The public posting describes a portfolio as {portfolio}.",
                source_url,
                observed_at,
            )
        )
    if employment_type != "unknown":
        evidence.append(
            _evidence(
                "employment_type",
                f"The title or exposed source metadata identifies the role as {employment_type}.",
                source_url,
                observed_at,
            )
        )

    return {
        "schema_version": 1,
        "id": f"{platform}:{company_id}:{_record_id_part(source_job_id)}",
        "source": {
            "platform": platform,
            "mode": "automatic",
            "source_job_id": source_job_id,
            "url": source_url,
        },
        "title": title,
        "company": {
            "id": company_id,
            "name": company_name,
        },
        "location": {
            "raw": raw_location,
            "places": places,
        },
        "work_arrangement": work_arrangement,
        "remote_eligibility": remote_eligibility,
        "employment_type": employment_type,
        "compensation": {
            "disclosed": False,
            "currency": None,
            "amount_min": None,
            "amount_max": None,
            "period": "unknown",
            "annual_pay_periods": None,
        },
        "experience": experience,
        "requirements": {
            "portfolio": portfolio,
        },
        "classification": {
            "role_families": [],
            "seniority": seniority,
            "people_management": people_management,
        },
        "summary": None,
        "dates": {
            "published_on": _iso_date(first_published),
            "first_seen_on": first_seen_on,
            "captured_at": observed_at,
        },
        "provenance": {
            "capture_method": "public_endpoint",
            "evidence": evidence[:50],
        },
        "privacy": {
            "visibility": "public_metadata",
            "raw_description": "not_stored",
            "contains_candidate_data": False,
        },
    }


def normalize_greenhouse_job(
    company,
    raw_job,
    *,
    first_seen_on,
    observed_at,
):
    """Build one Greenhouse record without retaining description HTML."""

    if not isinstance(raw_job, dict):
        return None
    return _build_public_job(
        company,
        platform="greenhouse",
        source_job_id=raw_job.get("source_job_id"),
        title=raw_job.get("title"),
        raw_location=raw_job.get("location"),
        source_url=raw_job.get("url"),
        description_html=raw_job.get("description_html"),
        metadata=raw_job.get("metadata"),
        first_published=raw_job.get("first_published"),
        first_seen_on=first_seen_on,
        observed_at=observed_at,
    )


def _workday_arrangement(value):
    words = _normalized_words(str(value or ""))
    if _has_phrase(words, "remote"):
        return "remote"
    if _has_phrase(words, "hybrid"):
        return "hybrid"
    if _has_phrase(words, "on site") or _has_phrase(words, "onsite"):
        return "onsite"
    return None


def _source_employment_type(value, title):
    combined = f"{value or ''} {title or ''}".lower()
    if re.search(r"\b(intern|internship)\b", combined):
        return "internship"
    if re.search(r"\bpart[- ]?time\b", combined):
        return "part_time"
    if re.search(r"\b(contract|contractor|fixed[- ]term)\b", combined):
        return "contract"
    if re.search(r"\btemporary\b", combined):
        return "temporary"
    if re.search(r"\bfull[- ]?time\b", combined):
        return "full_time"
    return None


def normalize_workday_job(
    company,
    raw_job,
    *,
    first_seen_on,
    observed_at,
):
    """Build one Workday record without retaining description HTML."""

    if not isinstance(raw_job, dict):
        return None
    return _build_public_job(
        company,
        platform="workday",
        source_job_id=raw_job.get("source_job_id"),
        title=raw_job.get("title"),
        raw_location=raw_job.get("location"),
        source_url=raw_job.get("url"),
        description_html=raw_job.get("description_html"),
        metadata=[],
        first_published=raw_job.get("first_published"),
        first_seen_on=first_seen_on,
        observed_at=observed_at,
        work_arrangement_override=_workday_arrangement(
            raw_job.get("remote_type")
        ),
        employment_type_override=_source_employment_type(
            raw_job.get("time_type"),
            raw_job.get("title"),
        ),
        country_code_overrides=raw_job.get("country_codes"),
    )


def _smartrecruiters_arrangement(remote, hybrid):
    if hybrid is True:
        return "hybrid"
    if remote is True:
        return "remote"
    if remote is False:
        return "onsite"
    return None


def normalize_smartrecruiters_job(
    company,
    raw_job,
    *,
    first_seen_on,
    observed_at,
):
    """Build one SmartRecruiters record without retaining description HTML."""

    if not isinstance(raw_job, dict):
        return None
    return _build_public_job(
        company,
        platform="smartrecruiters",
        source_job_id=raw_job.get("source_job_id"),
        title=raw_job.get("title"),
        raw_location=raw_job.get("location"),
        source_url=raw_job.get("url"),
        description_html=raw_job.get("description_html"),
        metadata=[],
        first_published=raw_job.get("first_published"),
        first_seen_on=first_seen_on,
        observed_at=observed_at,
        work_arrangement_override=_smartrecruiters_arrangement(
            raw_job.get("remote"),
            raw_job.get("hybrid"),
        ),
        employment_type_override=_source_employment_type(
            raw_job.get("employment_label"),
            raw_job.get("title"),
        ),
        country_code_overrides=raw_job.get("country_codes"),
    )
