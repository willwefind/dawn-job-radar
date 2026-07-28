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


ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "data", "jobs.json")
DOCS = os.path.join(ROOT, "docs")
TODAY = datetime.date.today().isoformat()

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
    )
    return [
        {
            "title": job.get("title", ""),
            "location": (job.get("location") or {}).get("name", ""),
            "url": job.get("absolute_url", ""),
        }
        for job in data.get("jobs", [])
    ]


def fetch_smartrecruiters(company):
    output = []
    offset = 0
    while True:
        data = http_json(
            f"https://api.smartrecruiters.com/v1/companies/{company['slug']}"
            f"/postings?limit=100&offset={offset}"
        )
        content = data.get("content", [])
        for posting in content:
            location = posting.get("location") or {}
            location_text = ", ".join(
                item
                for item in [location.get("city"), location.get("country")]
                if item
            )
            output.append(
                {
                    "title": posting.get("name", ""),
                    "location": location_text,
                    "url": (
                        "https://jobs.smartrecruiters.com/"
                        f"{company['slug']}/{posting.get('id', '')}"
                    ),
                }
            )
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
            path = job.get("externalPath", "")
            output.append(
                {
                    "title": job.get("title", ""),
                    "location": job.get("locationsText", ""),
                    "url": (
                        f"https://{workday['host']}/{workday['site']}{path}"
                        if path
                        else ""
                    ),
                }
            )
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
        "yy": datetime.date.today().strftime("%y/%m/%d"),
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

    jobs = []
    errors = []
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
            continue

        for raw_job in fetched:
            job = normalize_fetched_job(raw_job)
            if job is None or not keep(job, company):
                continue
            key = job_key(company["id"], job)
            previous = old.get(key)
            jobs.append(
                {
                    "key": key,
                    "company_id": company["id"],
                    "company": company["name"],
                    "track": company["track"],
                    "title": job["title"],
                    "location": job["location"],
                    "url": job["url"],
                    "first_seen": (
                        previous["first_seen"] if previous else TODAY
                    ),
                }
            )

    deduplicated = {}
    for job in jobs:
        if safe_http_url(job.get("url", "")):
            deduplicated[job["key"]] = job
    jobs = sorted(
        deduplicated.values(),
        key=lambda item: (item["first_seen"], item["company"]),
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

    render(jobs, errors, config)
    new_count = sum(1 for job in jobs if job["first_seen"] == TODAY)
    print(
        f"完成：{len(jobs)} 个职位在架，"
        f"今日新到 {new_count}，抓取失败 {len(errors)} 家"
    )
    for error in errors:
        print("  !", error)


if __name__ == "__main__":
    main()
