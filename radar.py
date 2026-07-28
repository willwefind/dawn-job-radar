# -*- coding: utf-8 -*-
"""dawn-job-radar · 职途显影
每日从各公司 ATS 公开接口拉取在招职位，合并进 data/jobs.json，
并输出 docs/jobs.js 供 docs/index.html（来自 template.html）渲染。
无第三方依赖，仅标准库。
"""
import json, os, shutil, hashlib, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "data", "jobs.json")
DOCS = os.path.join(ROOT, "docs")
TODAY = datetime.date.today().isoformat()

UA = {"User-Agent": "Mozilla/5.0 (dawn-job-radar; personal job feed)",
      "Content-Type": "application/json"}


def http_json(url, payload=None, timeout=25):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=UA,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------- 各 ATS 适配 ----------

def fetch_greenhouse(c):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs")
    return [{"title": j.get("title", ""),
             "location": (j.get("location") or {}).get("name", ""),
             "url": j.get("absolute_url", "")}
            for j in d.get("jobs", [])]


def fetch_smartrecruiters(c):
    out, offset = [], 0
    while True:
        d = http_json(f"https://api.smartrecruiters.com/v1/companies/{c['slug']}"
                      f"/postings?limit=100&offset={offset}")
        content = d.get("content", [])
        for p in content:
            loc = p.get("location") or {}
            loc_s = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x)
            out.append({"title": p.get("name", ""), "location": loc_s,
                        "url": f"https://jobs.smartrecruiters.com/{c['slug']}/{p.get('id', '')}"})
        offset += len(content)
        if not content or offset >= min(d.get("totalFound", 0), 300):
            break
    return out


def fetch_workday(c):
    w = c["workday"]
    base = f"https://{w['host']}/wday/cxs/{w['tenant']}/{w['site']}"
    out, offset, total = [], 0, None
    while True:
        d = http_json(f"{base}/jobs", {"appliedFacets": {}, "limit": 20,
                                       "offset": offset,
                                       "searchText": w.get("search_text", "")})
        total = d.get("total", 0) if total is None else total
        posts = d.get("jobPostings", [])
        for j in posts:
            path = j.get("externalPath", "")
            out.append({"title": j.get("title", ""),
                        "location": j.get("locationsText", ""),
                        "url": f"https://{w['host']}/{w['site']}{path}" if path else ""})
        offset += len(posts)
        if not posts or offset >= min(total, 200):
            break
    return out


FETCHERS = {"greenhouse": fetch_greenhouse,
            "smartrecruiters": fetch_smartrecruiters,
            "workday": fetch_workday}


# ---------- 过滤与合并 ----------

def keep(job, c):
    t = job["title"].lower()
    for kw in c.get("title_exclude", []):
        if kw.lower() in t:
            return False
    lks = c.get("location_keywords", [])
    if lks:
        loc = job["location"].lower()
        if not any(k.lower() in loc for k in lks):
            return False
    return True


def job_key(cid, job):
    raw = f"{cid}|{job['title']}|{job['location']}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]



import re as _re

STRONG_EARLY = _re.compile(r"\b(intern|internship|new grad|graduate|campus|university"
                           r"|early career|early in career|entry[- ]level)\b")
SENIOR = _re.compile(r"\b(senior|sr|staff|principal|lead|director|manager|head"
                     r"|vp|vice president|chief|distinguished|fellow)\b")
WEAK_EARLY = _re.compile(r"\b(junior|associate|coordinator|trainee|apprentice)\b")

def seniority(title):
    t = title.lower()
    if STRONG_EARLY.search(t):
        return 0
    if SENIOR.search(t):
        return 2
    if WEAK_EARLY.search(t):
        return 0
    return 1


TECH = _re.compile(r"\b(engineer|engineering|developer|software|scientist|research"
                   r"|machine learning|deep learning|data|backend|frontend|full[- ]stack"
                   r"|infrastructure|devops|sre|security|silicon|hardware|firmware"
                   r"|architect|kernel|compiler|physics|verification|asic|gpu|cuda"
                   r"|qa|test|reliability|network|cloud|database|analytics)\b")

def is_tech(title):
    return 1 if TECH.search(title.lower()) else 0

MOODS = ["外面的世界，冲洗好了一版", "今天也替你看了一圈", "灯还亮着，影子陆续浮出",
         "显影液换过了，很清", "风把新的消息吹进来了", "慢慢看，不急"]


def render(jobs, errors, cfg):
    tracks = []
    for c in cfg["companies"]:
        if c["track"] not in tracks:
            tracks.append(c["track"])
    mood = MOODS[int(hashlib.sha1(TODAY.encode()).hexdigest(), 16) % len(MOODS)]
    meta = {"updated": TODAY,
            "yy": datetime.date.today().strftime("%y/%m/%d"),
            "mood": mood,
            "new_n": sum(1 for j in jobs if j["first_seen"] == TODAY),
            "total": len(jobs), "tracks": tracks,
            "errors": [e.split(":")[0] for e in errors]}
    slim = [{"c": j["company"], "t": j["title"], "l": j["location"],
             "u": j["url"], "k": j["track"], "f": j["first_seen"], "s": seniority(j["title"]), "r": is_tech(j["title"])} for j in jobs]
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "jobs.js"), "w", encoding="utf-8") as f:
        f.write("window.META=" + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + ";")
        f.write("window.JOBS=" + json.dumps(slim, ensure_ascii=False, separators=(",", ":")) + ";")
    shutil.copyfile(os.path.join(ROOT, "template.html"),
                    os.path.join(DOCS, "index.html"))


def main():
    cfg = json.load(open(os.path.join(ROOT, "companies.json"), encoding="utf-8"))
    old = {}
    if os.path.exists(DATA_PATH):
        old = {j["key"]: j for j in json.load(open(DATA_PATH, encoding="utf-8"))["jobs"]}

    jobs, errors = [], []
    for c in cfg["companies"]:
        if c.get("ats") == "pending":
            continue
        try:
            fetched = FETCHERS[c["ats"]](c)
        except Exception as e:  # 单家失败不拖垮整趟班车
            errors.append(f"{c['name']}: {type(e).__name__} {e}")
            jobs.extend(j for j in old.values() if j["company_id"] == c["id"])
            continue
        for f in fetched:
            if not keep(f, c):
                continue
            k = job_key(c["id"], f)
            prev = old.get(k)
            jobs.append({"key": k, "company_id": c["id"], "company": c["name"],
                         "track": c["track"], "title": f["title"],
                         "location": f["location"], "url": f["url"],
                         "first_seen": prev["first_seen"] if prev else TODAY})

    dedup = {}
    for j in jobs:
        dedup[j["key"]] = j
    jobs = sorted(dedup.values(),
                  key=lambda x: (x["first_seen"], x["company"]), reverse=True)

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    json.dump({"updated": TODAY, "errors": errors, "jobs": jobs},
              open(DATA_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    render(jobs, errors, cfg)
    new_n = sum(1 for j in jobs if j["first_seen"] == TODAY)
    print(f"完成：{len(jobs)} 个职位在架，今日新到 {new_n}，抓取失败 {len(errors)} 家")
    for e in errors:
        print("  !", e)


if __name__ == "__main__":
    main()
