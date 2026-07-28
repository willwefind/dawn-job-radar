# -*- coding: utf-8 -*-
"""Validate and normalize manually supplied job records.

This importer is intentionally local-only. It does not access job platforms,
browser sessions, cookies, tokens, messages, or application forms.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


ROOT = Path(__file__).resolve().parent
SOURCE_CONFIG_PATH = ROOT / "sources.json"
DEFAULT_OUTPUT_PATH = ROOT / "local" / "jobs.normalized.json"
PRIVATE_OUTPUT_ROOTS = (ROOT / "local", ROOT / "data" / "inbox")
SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 5_000_000

ASSISTED_PLATFORMS = {"boss", "linkedin"}
PLATFORM_DOMAINS = {
    "boss": "zhipin.com",
    "linkedin": "linkedin.com",
}
CAPTURE_METHOD_TO_INPUT_METHOD = {
    "manual_entry": "manual_entry",
    "local_file": "local_file_import",
    "user_received_job_alert": "user_received_job_alert",
}

WORK_ARRANGEMENTS = {"onsite", "hybrid", "remote", "unknown"}
REMOTE_SCOPES = {"worldwide", "limited", "unknown", "not_applicable"}
EMPLOYMENT_TYPES = {
    "full_time",
    "part_time",
    "contract",
    "temporary",
    "internship",
    "freelance",
    "unknown",
}
PAY_PERIODS = {"hour", "day", "week", "month", "year", "project"}
SENIORITY_LEVELS = {
    "entry",
    "junior",
    "mid",
    "senior",
    "leadership",
    "unknown",
}
MANAGEMENT_VALUES = {"required", "not_required", "unknown"}
PORTFOLIO_VALUES = {"required", "preferred", "not_mentioned", "unknown"}

ALLOWED_INPUT_KEYS = {
    "source",
    "capture_method",
    "source_job_id",
    "url",
    "title",
    "company",
    "location_raw",
    "city",
    "region",
    "country_code",
    "work_arrangement",
    "remote_scope",
    "allowed_countries",
    "allowed_regions",
    "employment_type",
    "currency",
    "salary_min",
    "salary_max",
    "pay_period",
    "annual_pay_periods",
    "experience_min_years",
    "experience_max_years",
    "portfolio",
    "role_families",
    "seniority",
    "people_management",
    "summary",
    "published_on",
}

SENSITIVE_KEY_PARTS = {
    "api_key",
    "authorization",
    "candidate_email",
    "candidate_name",
    "cookie",
    "credential",
    "cv",
    "email",
    "password",
    "phone",
    "refresh_token",
    "resume",
    "secret",
    "session",
    "token",
}
SENSITIVE_QUERY_PARTS = {
    "access_token",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
}
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\w)\+\d[\d\s().-]{6,}\d(?!\w)"),
)
ROLE_FAMILY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]+$")
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")


class ImportValidationError(ValueError):
    """Raised when imported content violates the intake contract."""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_path(path: Path) -> Path:
    """Allow writes only inside repository directories already ignored by Git."""
    resolved = path.expanduser().resolve()
    if not any(_is_within(resolved, root.resolve()) for root in PRIVATE_OUTPUT_ROOTS):
        allowed = ", ".join(str(root.relative_to(ROOT)) + "/" for root in PRIVATE_OUTPUT_ROOTS)
        raise ImportValidationError(
            f"output must stay inside a private ignored directory: {allowed}"
        )
    return resolved


def _scan_sensitive_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                raise ImportValidationError(f"{path}.{key}: sensitive field is not accepted")
            _scan_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_sensitive_keys(child, f"{path}[{index}]")


def _require_text(
    value: Any,
    field: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ImportValidationError(f"{field}: expected text")
    cleaned = value.strip()
    if not allow_empty and not cleaned:
        raise ImportValidationError(f"{field}: value is required")
    if len(cleaned) > max_length:
        raise ImportValidationError(f"{field}: exceeds {max_length} characters")
    return cleaned


def _optional_text(value: Any, field: str, *, max_length: int) -> str | None:
    if value is None:
        return None
    return _require_text(value, field, max_length=max_length)


def _reject_contact_text(value: str | None, field: str) -> None:
    if not value:
        return
    if EMAIL_PATTERN.search(value):
        raise ImportValidationError(f"{field}: email addresses are not accepted")
    if any(pattern.search(value) for pattern in PHONE_PATTERNS):
        raise ImportValidationError(f"{field}: phone numbers are not accepted")


def _optional_int(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportValidationError(f"{field}: expected an integer")
    if not minimum <= value <= maximum:
        raise ImportValidationError(f"{field}: expected {minimum}–{maximum}")
    return value


def _optional_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportValidationError(f"{field}: expected a number")
    if value < 0:
        raise ImportValidationError(f"{field}: cannot be negative")
    return value


def _enum(value: Any, field: str, allowed: set[str], default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise ImportValidationError(
            f"{field}: expected one of {', '.join(sorted(allowed))}"
        )
    return value


def _country_codes(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImportValidationError(f"{field}: expected a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not COUNTRY_CODE_PATTERN.fullmatch(item):
            raise ImportValidationError(
                f"{field}[{index}]: expected a two-letter uppercase country code"
            )
        if item not in result:
            result.append(item)
    return result


def _regions(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImportValidationError(f"{field}: expected a list")
    result: list[str] = []
    for index, item in enumerate(value):
        region = _require_text(item, f"{field}[{index}]", max_length=80)
        if region not in result:
            result.append(region)
    return result


def _role_families(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImportValidationError("role_families: expected a list")
    result: list[str] = []
    for index, item in enumerate(value):
        family = _require_text(item, f"role_families[{index}]", max_length=80)
        if not ROLE_FAMILY_PATTERN.fullmatch(family):
            raise ImportValidationError(
                f"role_families[{index}]: use lowercase letters, numbers, hyphens or underscores"
            )
        if family not in result:
            result.append(family)
    return result


def _validate_source_url(value: Any, platform: str) -> str:
    url = _require_text(value, "url", max_length=2000)
    _reject_contact_text(url, "url")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ImportValidationError("url: only complete HTTPS URLs are accepted")
    if parsed.username is not None or parsed.password is not None:
        raise ImportValidationError("url: embedded credentials are not accepted")

    hostname = parsed.hostname.lower().rstrip(".")
    expected_domain = PLATFORM_DOMAINS[platform]
    if hostname != expected_domain and not hostname.endswith("." + expected_domain):
        raise ImportValidationError(
            f"url: {platform} imports must use an official {expected_domain} host"
        )
    if hostname == "localhost":
        raise ImportValidationError("url: local hosts are not accepted")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ImportValidationError("url: private or reserved IP addresses are not accepted")

    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower().replace("-", "_")
        if any(part in normalized for part in SENSITIVE_QUERY_PARTS):
            raise ImportValidationError("url: sensitive authentication query parameters are not accepted")
    return url


def _load_source_registry(path: Path = SOURCE_CONFIG_PATH) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportValidationError("sources.json could not be loaded") from exc
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ImportValidationError("sources.json: sources must be a list")
    return {
        item["id"]: item
        for item in sources
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _validate_platform_and_method(
    platform: Any,
    capture_method: Any,
    registry: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    platform = _require_text(platform, "source", max_length=40).lower()
    if platform not in ASSISTED_PLATFORMS:
        raise ImportValidationError(
            "source: v1 manual import currently accepts only boss or linkedin"
        )
    config = registry.get(platform)
    if not config or config.get("mode") != "assisted":
        raise ImportValidationError(f"source: {platform} is not configured for assisted import")

    capture_method = _enum(
        capture_method,
        "capture_method",
        set(CAPTURE_METHOD_TO_INPUT_METHOD),
        "manual_entry",
    )
    required_input_method = CAPTURE_METHOD_TO_INPUT_METHOD[capture_method]
    if required_input_method not in config.get("input_methods", []):
        raise ImportValidationError(
            f"capture_method: {capture_method} is not enabled for {platform}"
        )
    return platform, capture_method


def _validate_date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    value = _require_text(value, field, max_length=10)
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ImportValidationError(f"{field}: expected YYYY-MM-DD") from exc
    return parsed.isoformat()


def _company_id(name: str) -> str | None:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    return slug[:100] or None


def _stable_id(platform: str, source_job_id: str | None, url: str) -> str:
    seed = source_job_id or url
    digest = hashlib.sha256(f"{platform}|{seed}".encode("utf-8")).hexdigest()[:20]
    return f"{platform}:{digest}"


def _evidence(
    field: str,
    summary: str,
    source_url: str,
    observed_at: str,
) -> dict[str, str]:
    return {
        "field": field,
        "summary": summary,
        "source_url": source_url,
        "observed_at": observed_at,
    }


def normalize_record(
    raw: Any,
    *,
    registry: dict[str, dict[str, Any]],
    observed_at: dt.datetime,
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ImportValidationError(f"jobs[{index}]: expected an object")
    _scan_sensitive_keys(raw, f"jobs[{index}]")
    extra = sorted(set(raw) - ALLOWED_INPUT_KEYS)
    if extra:
        raise ImportValidationError(
            f"jobs[{index}]: unsupported fields: {', '.join(extra)}"
        )

    platform, capture_method = _validate_platform_and_method(
        raw.get("source"), raw.get("capture_method"), registry
    )
    url = _validate_source_url(raw.get("url"), platform)
    source_job_id = _optional_text(
        raw.get("source_job_id"), "source_job_id", max_length=200
    )
    title = _require_text(raw.get("title"), "title", max_length=300)
    company_name = _require_text(raw.get("company"), "company", max_length=200)
    location_raw = _require_text(
        raw.get("location_raw"), "location_raw", max_length=500
    )
    _reject_contact_text(title, "title")
    _reject_contact_text(company_name, "company")
    _reject_contact_text(location_raw, "location_raw")

    city = _optional_text(raw.get("city"), "city", max_length=120)
    region = _optional_text(raw.get("region"), "region", max_length=120)
    country_code = raw.get("country_code")
    if country_code is not None:
        if not isinstance(country_code, str) or not COUNTRY_CODE_PATTERN.fullmatch(
            country_code
        ):
            raise ImportValidationError(
                "country_code: expected a two-letter uppercase country code"
            )
    places = []
    if any(item is not None for item in (city, region, country_code)):
        places.append(
            {"city": city, "region": region, "country_code": country_code}
        )

    work_arrangement = _enum(
        raw.get("work_arrangement"),
        "work_arrangement",
        WORK_ARRANGEMENTS,
        "unknown",
    )
    default_scope = "not_applicable" if work_arrangement == "onsite" else "unknown"
    remote_scope = _enum(
        raw.get("remote_scope"),
        "remote_scope",
        REMOTE_SCOPES,
        default_scope,
    )
    allowed_countries = _country_codes(
        raw.get("allowed_countries"), "allowed_countries"
    )
    allowed_regions = _regions(raw.get("allowed_regions"), "allowed_regions")

    if work_arrangement == "onsite":
        if remote_scope != "not_applicable" or allowed_countries or allowed_regions:
            raise ImportValidationError(
                "onsite jobs must use remote_scope=not_applicable with no remote regions"
            )
    elif remote_scope == "not_applicable":
        raise ImportValidationError(
            "remote_scope=not_applicable is allowed only for onsite jobs"
        )
    if remote_scope == "limited" and not (allowed_countries or allowed_regions):
        raise ImportValidationError(
            "remote_scope=limited requires allowed_countries or allowed_regions"
        )
    if remote_scope in {"worldwide", "unknown"} and (
        allowed_countries or allowed_regions
    ):
        raise ImportValidationError(
            f"remote_scope={remote_scope} cannot include allowed countries or regions"
        )

    employment_type = _enum(
        raw.get("employment_type"),
        "employment_type",
        EMPLOYMENT_TYPES,
        "unknown",
    )

    salary_min = _optional_number(raw.get("salary_min"), "salary_min")
    salary_max = _optional_number(raw.get("salary_max"), "salary_max")
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise ImportValidationError("salary_min cannot exceed salary_max")
    salary_disclosed = salary_min is not None or salary_max is not None
    currency = _optional_text(raw.get("currency"), "currency", max_length=3)
    if currency is not None and not re.fullmatch(r"[A-Z]{3}", currency):
        raise ImportValidationError("currency: expected a three-letter uppercase code")
    pay_period = raw.get("pay_period")
    annual_pay_periods = _optional_int(
        raw.get("annual_pay_periods"),
        "annual_pay_periods",
        minimum=1,
        maximum=24,
    )
    if salary_disclosed:
        if currency is None or pay_period not in PAY_PERIODS:
            raise ImportValidationError(
                "disclosed salary requires currency and a valid pay_period"
            )
        if annual_pay_periods is not None and pay_period != "month":
            raise ImportValidationError(
                "annual_pay_periods is allowed only for monthly salary"
            )
    elif currency is not None or pay_period is not None or annual_pay_periods is not None:
        raise ImportValidationError(
            "currency, pay_period and annual_pay_periods require a disclosed salary amount"
        )

    experience_min = _optional_int(
        raw.get("experience_min_years"),
        "experience_min_years",
        minimum=0,
        maximum=60,
    )
    experience_max = _optional_int(
        raw.get("experience_max_years"),
        "experience_max_years",
        minimum=0,
        maximum=60,
    )
    if (
        experience_min is not None
        and experience_max is not None
        and experience_min > experience_max
    ):
        raise ImportValidationError(
            "experience_min_years cannot exceed experience_max_years"
        )
    experience_explicit = experience_min is not None or experience_max is not None

    portfolio = _enum(
        raw.get("portfolio"),
        "portfolio",
        PORTFOLIO_VALUES,
        "unknown",
    )
    role_families = _role_families(raw.get("role_families"))
    seniority = _enum(
        raw.get("seniority"), "seniority", SENIORITY_LEVELS, "unknown"
    )
    people_management = _enum(
        raw.get("people_management"),
        "people_management",
        MANAGEMENT_VALUES,
        "unknown",
    )

    summary = _optional_text(raw.get("summary"), "summary", max_length=600)
    _reject_contact_text(summary, "summary")

    published_on = _validate_date(raw.get("published_on"), "published_on")
    observed_at = observed_at.astimezone(dt.timezone.utc)
    captured_at = observed_at.isoformat().replace("+00:00", "Z")
    first_seen_on = observed_at.date().isoformat()

    evidence = [
        _evidence(
            "location",
            f"Manual intake records the source location as {location_raw}.",
            url,
            captured_at,
        ),
        _evidence(
            "work_arrangement",
            f"Manual intake classifies the work arrangement as {work_arrangement}.",
            url,
            captured_at,
        ),
    ]
    if remote_scope not in {"unknown", "not_applicable"}:
        evidence.append(
            _evidence(
                "remote_eligibility",
                f"Manual intake records remote eligibility scope as {remote_scope}.",
                url,
                captured_at,
            )
        )
    if experience_explicit:
        evidence.append(
            _evidence(
                "experience",
                "Manual intake includes an explicit experience-year requirement.",
                url,
                captured_at,
            )
        )
    if salary_disclosed:
        evidence.append(
            _evidence(
                "compensation",
                "Manual intake includes a disclosed compensation range.",
                url,
                captured_at,
            )
        )
    if portfolio != "unknown":
        evidence.append(
            _evidence(
                "requirements.portfolio",
                f"Manual intake records the portfolio requirement as {portfolio}.",
                url,
                captured_at,
            )
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "id": _stable_id(platform, source_job_id, url),
        "source": {
            "platform": platform,
            "mode": "assisted",
            "source_job_id": source_job_id,
            "url": url,
        },
        "title": title,
        "company": {"id": _company_id(company_name), "name": company_name},
        "location": {"raw": location_raw, "places": places},
        "work_arrangement": work_arrangement,
        "remote_eligibility": {
            "scope": remote_scope,
            "allowed_countries": allowed_countries,
            "allowed_regions": allowed_regions,
        },
        "employment_type": employment_type,
        "compensation": {
            "disclosed": salary_disclosed,
            "currency": currency if salary_disclosed else None,
            "amount_min": salary_min,
            "amount_max": salary_max,
            "period": pay_period if salary_disclosed else "unknown",
            "annual_pay_periods": annual_pay_periods if salary_disclosed else None,
        },
        "experience": {
            "min_years": experience_min,
            "max_years": experience_max,
            "explicit": experience_explicit,
        },
        "requirements": {"portfolio": portfolio},
        "classification": {
            "role_families": role_families,
            "seniority": seniority,
            "people_management": people_management,
        },
        "summary": summary,
        "dates": {
            "published_on": published_on,
            "first_seen_on": first_seen_on,
            "captured_at": captured_at,
        },
        "provenance": {
            "capture_method": capture_method,
            "evidence": evidence,
        },
        "privacy": {
            "visibility": "local_only",
            "raw_description": "not_stored",
            "contains_candidate_data": False,
        },
    }


def normalize_payload(
    payload: Any,
    *,
    registry: dict[str, dict[str, Any]] | None = None,
    observed_at: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if set(payload) != {"jobs"}:
            raise ImportValidationError("top-level object must contain only a jobs list")
        records = payload["jobs"]
    else:
        records = payload
    if not isinstance(records, list):
        raise ImportValidationError("input must be a list or an object containing a jobs list")
    if len(records) > 500:
        raise ImportValidationError("one import may contain at most 500 jobs")

    registry = registry or _load_source_registry()
    observed_at = observed_at or dt.datetime.now(dt.timezone.utc)
    result: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(records):
        normalized = normalize_record(
            raw,
            registry=registry,
            observed_at=observed_at,
            index=index,
        )
        previous = seen.get(normalized["id"])
        if previous is not None:
            if previous != normalized:
                raise ImportValidationError(
                    f"jobs[{index}]: conflicts with another record for the same source job"
                )
            continue
        seen[normalized["id"]] = normalized
        result.append(normalized)
    return result


def load_payload(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ImportValidationError("input file exceeds the 5 MB safety limit")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except ImportValidationError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportValidationError("input file could not be read as UTF-8 JSON") from exc


def write_private_json(path: Path, jobs: list[dict[str, Any]], *, force: bool) -> None:
    output = validate_output_path(path)
    if output.exists() and not force:
        raise ImportValidationError("output already exists; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=".job-import-",
            suffix=".json",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(jobs, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, output)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and normalize local BOSS/LinkedIn job records."
    )
    parser.add_argument("input", type=Path, help="UTF-8 JSON input file")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="private output path under local/ or data/inbox/",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate and normalize in memory without writing a file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing private output file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = load_payload(args.input)
        jobs = normalize_payload(payload)
        if not args.check_only:
            write_private_json(args.output, jobs, force=args.force)
    except ImportValidationError as exc:
        print(f"Import rejected: {exc}", file=os.sys.stderr)
        return 2

    action = "Validated" if args.check_only else "Imported"
    print(f"{action} {len(jobs)} local job record(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
