# -*- coding: utf-8 -*-
"""dawn-job-radar · 职途显影

Collect public job metadata from supported ATS endpoints, retain first-seen
dates, and render the static public feed. Candidate-fit evaluation belongs to
the local screening layer and must not be inferred here.

The module uses only Python's standard library.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from job_facts import (
    normalize_greenhouse_job,
    normalize_smartrecruiters_job,
    normalize_workday_job,
)


ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "data", "jobs.json")
NORMALIZED_DATA_PATH = os.path.join(ROOT, "data", "jobs.normalized.json")
DOCS = os.path.join(ROOT, "docs")


def today_in_timezone(timezone_name, now=None):
    """Return the calendar date for an explicit IANA timezone."""

    try:
        timezone = ZoneInfo(str(timezone_name))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(
            f"RADAR_TIMEZONE is not a valid IANA timezone: {timezone_name}"
        ) from error
    instant = now or datetime.datetime.now(datetime.timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must include timezone information")
    return instant.astimezone(timezone).date().isoformat()


RADAR_TIMEZONE = os.environ.get("RADAR_TIMEZONE", "UTC")
TODAY = today_in_timezone(RADAR_TIMEZONE)

UA = {
    "User-Agent": "dawn-job-radar/1.0 (public job feed)",
    "Accept": "application/json",
}


def safe_http_url(value):
    """Return a stripped public HTTP(S) URL, or an empty string if unsafe."""

    if not isinstance(value, str):
        return ""
    value = value.strip()
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return value


def normalize_fetched_job(job):
    """Normalize the public fields shared by all source adapters."""

    if not isinstance(job, dict):
        return None
    title = str(job.get("title") or "").strip()
    location = str(job.get("location") or "").strip()
    url = safe_http_url(job.get("url"))
    if not title or not url:
        return None
    return {"title": title, "location": location, "url": url}


def http_json(url, payload=None, timeout=25):
    url = safe_http_url(url)
    if not url:
        raise ValueError("ATS endpoint must be a public HTTP(S) URL")
    data = json.dumps(payload).encode() if payload is not None else None
    headers = dict(UA)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


# ---------- ATS adapters ----------


def fetch_greenhouse(company):
    data = http_json(
        f"https://boards-api.greenhouse.io/v1/boards/{company['slug']}/jobs"
        "?content=true"
    )
    return [
        {
            "source_job_id": str(job.get("id") or ""),
            "title": job.get("title", ""),
            "location": (job.get("location") or {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "description_html": job.get("content", ""),
            "metadata": job.get("metadata") or [],
            "first_published": job.get("first_published"),
        }
        for job in data.get("jobs", [])
    ]


def fetch_smartrecruiters(company):
    slug = urllib.parse.quote(str(company["slug"]), safe="")
    base = (
        "https://api.smartrecruiters.com/v1/companies/"
        f"{slug}/postings"
    )
    output = []
    offset = 0
    detail_count = 0
    try:
        detail_limit = int(company.get("detail_limit", 80))
    except (TypeError, ValueError):
        detail_limit = 80
    detail_limit = max(0, min(detail_limit, 100))
    while True:
        data = http_json(
            f"{base}?limit=100&offset={offset}"
        )
        content = data.get("content", [])
        for posting in content:
            location = posting.get("location") or {}
            location_text = str(location.get("fullLocation") or "").strip()
            if not location_text:
                location_text = ", ".join(
                    str(item).strip()
                    for item in [
                        location.get("city"),
                        location.get("region"),
                        location.get("country"),
                    ]
                    if str(item or "").strip()
                )
            source_job_id = str(
                posting.get("id") or posting.get("uuid") or ""
            )
            public_url = (
                f"https://jobs.smartrecruiters.com/{slug}/{source_job_id}"
                if source_job_id
                else ""
            )
            summary = {
                "source_job_id": source_job_id,
                "title": posting.get("name", ""),
                "location": location_text,
                "url": public_url,
                "description_html": "",
                "first_published": posting.get("releasedDate"),
                "employment_label": (
                    posting.get("typeOfEmployment") or {}
                ).get("label"),
                "remote": location.get("remote"),
                "hybrid": location.get("hybrid"),
                "country_codes": [
                    str(location["country"]).upper()
                ]
                if isinstance(location.get("country"), str)
                and len(location["country"]) == 2
                else [],
                "detail_status": "limit",
            }
            if (
                not normalize_fetched_job(summary)
                or not keep(summary, company)
            ):
                continue

            enriched = dict(summary)
            if source_job_id and detail_count < detail_limit:
                detail_count += 1
                try:
                    detail = http_json(f"{base}/{source_job_id}")
                    if detail.get("active") is False:
                        continue
                    detail_location = detail.get("location") or {}
                    sections = (
                        (detail.get("jobAd") or {}).get("sections") or {}
                    )
                    description_html = "\n".join(
                        str((sections.get(name) or {}).get("text") or "")
                        for name in (
                            "jobDescription",
                            "qualifications",
                            "additionalInformation",
                        )
                    )
                    detail_country = detail_location.get("country")
                    country_codes = (
                        [str(detail_country).upper()]
                        if isinstance(detail_country, str)
                        and len(detail_country) == 2
                        else summary["country_codes"]
                    )
                    detail_location_text = str(
                        detail_location.get("fullLocation") or ""
                    ).strip()
                    if not detail_location_text:
                        detail_location_text = summary["location"]
                    enriched.update(
                        {
                            "source_job_id": str(
                                detail.get("id")
                                or detail.get("uuid")
                                or source_job_id
                            ),
                            "title": detail.get("name")
                            or summary["title"],
                            "location": detail_location_text,
                            "url": detail.get("applyUrl")
                            or summary["url"],
                            "description_html": description_html,
                            "first_published": detail.get("releasedDate")
                            or summary["first_published"],
                            "employment_label": (
                                detail.get("typeOfEmployment") or {}
                            ).get("label")
                            or summary["employment_label"],
                            "remote": detail_location.get(
                                "remote", summary["remote"]
                            ),
                            "hybrid": detail_location.get(
                                "hybrid", summary["hybrid"]
                            ),
                            "country_codes": country_codes,
                            "detail_status": "ok",
                        }
                    )
                except Exception:
                    enriched["detail_status"] = "unavailable"
            output.append(enriched)
        offset += len(content)
        if not content or offset >= min(data.get("totalFound", 0), 300):
            break
    return output


def fetch_workday(company):
    workday = company["workday"]
    base = (
        f"https://{workday['host']}/wday/cxs/"
        f"{workday['tenant']}/{workday['site']}"
    )
    output = []
    offset = 0
    total = None
    detail_count = 0
    try:
        detail_limit = int(company.get("detail_limit", 60))
    except (TypeError, ValueError):
        detail_limit = 60
    detail_limit = max(0, min(detail_limit, 100))
    while True:
        data = http_json(
            f"{base}/jobs",
            {
                "appliedFacets": {},
                "limit": 20,
                "offset": offset,
                "searchText": workday.get("search_text", ""),
            },
        )
        total = data.get("total", 0) if total is None else total
        postings = data.get("jobPostings", [])
        for job in postings:
            path = str(job.get("externalPath") or "")
            summary = {
                "title": job.get("title", ""),
                "location": job.get("locationsText", ""),
                "url": (
                    f"https://{workday['host']}/{workday['site']}{path}"
                    if path.startswith("/job/")
                    else ""
                ),
            }
            if not normalize_fetched_job(summary) or not keep(summary, company):
                continue

            source_fallback = hashlib.sha1(path.encode()).hexdigest()[:16]
            enriched = {
                **summary,
                "source_job_id": source_fallback,
                "description_html": "",
                "first_published": None,
                "time_type": None,
                "remote_type": None,
                "country_codes": [],
                "detail_status": "limit",
            }
            if path.startswith("/job/") and detail_count < detail_limit:
                detail_count += 1
                try:
                    detail = http_json(f"{base}{path}")
                    posting = detail.get("jobPostingInfo") or {}
                    if posting.get("canApply") is False:
                        continue
                    requisition_location = (
                        posting.get("jobRequisitionLocation") or {}
                    )
                    country = requisition_location.get("country") or {}
                    country_code = country.get("alpha2Code")
                    country_codes = (
                        [country_code]
                        if isinstance(country_code, str)
                        and len(country_code) == 2
                        else []
                    )
                    enriched.update(
                        {
                            "source_job_id": (
                                str(
                                    posting.get("jobReqId")
                                    or posting.get("jobPostingId")
                                    or posting.get("id")
                                    or source_fallback
                                )
                            ),
                            "title": posting.get("title")
                            or summary["title"],
                            "location": posting.get("location")
                            or requisition_location.get("descriptor")
                            or summary["location"],
                            "url": posting.get("externalUrl")
                            or summary["url"],
                            "description_html": posting.get(
                                "jobDescription", ""
                            ),
                            "first_published": posting.get("startDate"),
                            "time_type": posting.get("timeType"),
                            "remote_type": posting.get("remoteType"),
                            "country_codes": country_codes,
                            "detail_status": "ok",
                        }
                    )
                except Exception:
                    enriched["detail_status"] = "unavailable"
            output.append(enriched)
        offset += len(postings)
        if not postings or offset >= min(total, 200):
            break
    return output


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
}


# ---------- Collection scope and public hints ----------


def keep(job, company):
    """Apply legacy collection scope, not candidate-fit evaluation."""

    title = job["title"].lower()
    for keyword in company.get("title_exclude", []):
        if keyword.lower() in title:
            return False
    location_keywords = company.get("location_keywords", [])
    if location_keywords:
        location = job["location"].lower()
        if not any(keyword.lower() in location for keyword in location_keywords):
            return False
    return True


def job_key(company_id, job):
    raw = f"{company_id}|{job['title']}|{job['location']}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


STRONG_EARLY = re.compile(
    r"\b(intern|internship|new grad|graduate|campus|university"
    r"|early career|early in career|entry[- ]level)\b"
)
SENIOR = re.compile(
    r"\b(senior|sr|staff|principal|lead|director|manager|head"
    r"|vp|vice president|chief|distinguished|fellow)\b"
)
WEAK_EARLY = re.compile(
    r"\b(junior|associate|coordinator|trainee|apprentice)\b"
)


def seniority(title):
    """Return a title signal only: 0 early, 1 unknown, 2 senior."""

    title = title.lower()
    if STRONG_EARLY.search(title):
        return 0
    if SENIOR.search(title):
        return 2
    if WEAK_EARLY.search(title):
        return 0
    return 1


TECH = re.compile(
    r"\b(engineer|engineering|developer|software|scientist|research"
    r"|machine learning|deep learning|data|backend|frontend|full[- ]stack"
    r"|infrastructure|devops|sre|security|silicon|hardware|firmware"
    r"|architect|kernel|compiler|physics|verification|asic|gpu|cuda"
    r"|qa|test|reliability|network|cloud|database|analytics)\b"
)


def is_tech(title):
    """Return a title signal only; this is not a candidate-fit decision."""

    return 1 if TECH.search(title.lower()) else 0


MOODS = [
    "外面的世界，冲洗好了一版",
    "今天也替你看了一圈",
    "灯还亮着，影子陆续浮出",
    "显影液换过了，很清",
    "风把新的消息吹进来了",
    "慢慢看，不急",
]


def render(jobs, errors, config):
    tracks = []
    for company in config["companies"]:
        if company["track"] not in tracks:
            tracks.append(company["track"])

    public_jobs = [
        job for job in jobs if safe_http_url(job.get("url", ""))
    ]
    mood = MOODS[
        int(hashlib.sha1(TODAY.encode()).hexdigest(), 16) % len(MOODS)
    ]
    meta = {
        "updated": TODAY,
        "yy": datetime.date.fromisoformat(TODAY).strftime("%y/%m/%d"),
        "mood": mood,
        "new_n": sum(
            1 for job in public_jobs if job["first_seen"] == TODAY
        ),
        "total": len(public_jobs),
        "tracks": tracks,
        "errors": [error.split(":")[0] for error in errors],
    }
    slim = [
        {
            "c": job["company"],
            "t": job["title"],
            "l": job["location"],
            "u": safe_http_url(job["url"]),
            "k": job["track"],
            "f": job["first_seen"],
            "s": seniority(job["title"]),
            "r": is_tech(job["title"]),
        }
        for job in public_jobs
    ]

    os.makedirs(DOCS, exist_ok=True)
    with open(
        os.path.join(DOCS, "jobs.js"), "w", encoding="utf-8"
    ) as output:
        output.write(
            "window.META="
            + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
            + ";"
        )
        output.write(
            "window.JOBS="
            + json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
            + ";"
        )
    shutil.copyfile(
        os.path.join(ROOT, "template.html"),
        os.path.join(DOCS, "index.html"),
    )


def _load_normalized_jobs():
    if not os.path.exists(NORMALIZED_DATA_PATH):
        return {}
    with open(NORMALIZED_DATA_PATH, encoding="utf-8") as source:
        payload = json.load(source)
    records = payload.get("jobs", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("normalized job data must be a list or jobs envelope")
    return {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def _write_public_snapshot(records, updated):
    """Write public normalized facts as a same-origin, no-fetch script."""

    payload = {
        "schema_version": 1,
        "updated": updated,
        "jobs": records,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    serialized = (
        serialized.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    os.makedirs(DOCS, exist_ok=True)
    with open(
        os.path.join(DOCS, "jobs.normalized.js"),
        "w",
        encoding="utf-8",
    ) as output:
        output.write(
            "window.JOB_RADAR_PUBLIC_SNAPSHOT="
            + serialized
            + ";\n"
        )


def _captured_at():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main():
    with open(
        os.path.join(ROOT, "companies.json"), encoding="utf-8"
    ) as source:
        config = json.load(source)

    old = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as source:
            old = {
                job["key"]: job
                for job in json.load(source)["jobs"]
            }
    old_normalized = _load_normalized_jobs()

    jobs = []
    normalized_jobs = []
    errors = []
    normalization_skipped = 0
    detail_degraded = 0
    observed_at = _captured_at()
    for company in config["companies"]:
        if company.get("ats") == "pending":
            continue
        try:
            fetched = FETCHERS[company["ats"]](company)
        except Exception as error:  # One source must not stop the full run.
            errors.append(
                f"{company['name']}: {type(error).__name__} {error}"
            )
            jobs.extend(
                job
                for job in old.values()
                if job["company_id"] == company["id"]
                and safe_http_url(job.get("url", ""))
            )
            if company.get("ats") in {
                "greenhouse",
                "smartrecruiters",
                "workday",
            }:
                normalized_jobs.extend(
                    record
                    for record in old_normalized.values()
                    if record.get("company", {}).get("id") == company["id"]
                )
            continue

        for raw_job in fetched:
            if (
                company.get("ats") in {"smartrecruiters", "workday"}
                and raw_job.get("detail_status") != "ok"
            ):
                detail_degraded += 1
            job = normalize_fetched_job(raw_job)
            if job is None or not keep(job, company):
                continue
            key = job_key(company["id"], job)
            previous = old.get(key)
            first_seen_on = (
                previous["first_seen"] if previous else TODAY
            )
            jobs.append(
                {
                    "key": key,
                    "company_id": company["id"],
                    "company": company["name"],
                    "track": company["track"],
                    "title": job["title"],
                    "location": job["location"],
                    "url": job["url"],
                    "first_seen": first_seen_on,
                }
            )
            if company.get("ats") == "greenhouse":
                normalized = normalize_greenhouse_job(
                    company,
                    raw_job,
                    first_seen_on=first_seen_on,
                    observed_at=observed_at,
                )
            elif company.get("ats") == "smartrecruiters":
                normalized = normalize_smartrecruiters_job(
                    company,
                    raw_job,
                    first_seen_on=first_seen_on,
                    observed_at=observed_at,
                )
            elif company.get("ats") == "workday":
                normalized = normalize_workday_job(
                    company,
                    raw_job,
                    first_seen_on=first_seen_on,
                    observed_at=observed_at,
                )
            else:
                normalized = None
            if company.get("ats") in {
                "greenhouse",
                "smartrecruiters",
                "workday",
            }:
                if normalized is None:
                    normalization_skipped += 1
                else:
                    normalized_jobs.append(normalized)

    deduplicated = {}
    for job in jobs:
        if safe_http_url(job.get("url", "")):
            deduplicated[job["key"]] = job
    jobs = sorted(
        deduplicated.values(),
        key=lambda item: (item["first_seen"], item["company"]),
        reverse=True,
    )
    normalized_jobs = sorted(
        {
            record["id"]: record
            for record in normalized_jobs
        }.values(),
        key=lambda record: (
            record["dates"]["first_seen_on"],
            record["company"]["name"],
            record["id"],
        ),
        reverse=True,
    )

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as output:
        json.dump(
            {"updated": TODAY, "errors": errors, "jobs": jobs},
            output,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    with open(NORMALIZED_DATA_PATH, "w", encoding="utf-8") as output:
        json.dump(
            normalized_jobs,
            output,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    _write_public_snapshot(normalized_jobs, TODAY)
    render(jobs, errors, config)
    new_count = sum(1 for job in jobs if job["first_seen"] == TODAY)
    print(
        f"完成：{len(jobs)} 个职位在架，"
        f"今日新到 {new_count}，抓取失败 {len(errors)} 家；"
        f"标准化 {len(normalized_jobs)} 个，"
        f"跳过 {normalization_skipped} 个，"
        f"ATS 详情降级 {detail_degraded} 个"
    )
    for error in errors:
        print("  !", error)


if __name__ == "__main__":
    main()
