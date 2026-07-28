import json
import unittest

import job_facts


COMPANY = {
    "id": "example-studio",
    "name": "Example Studio",
}
OBSERVED_AT = "2026-07-28T10:30:00Z"


def raw_job(**overrides):
    job = {
        "source_job_id": "1001",
        "title": "Junior Visual Designer",
        "location": "Remote, United States",
        "url": "https://job-boards.greenhouse.io/example/jobs/1001",
        "description_html": (
            "<h2>Requirements</h2>"
            "<ul><li>3+ years of visual design experience.</li>"
            "<li>Please submit a portfolio with the application.</li></ul>"
        ),
        "metadata": [],
        "first_published": "2026-07-26T12:00:00Z",
    }
    job.update(overrides)
    return job


def raw_workday_job(**overrides):
    job = {
        "source_job_id": "JR1001",
        "title": "Visual Design Coordinator",
        "location": "China, Beijing",
        "url": (
            "https://example.wd5.myworkdayjobs.com/External/"
            "job/China-Beijing/Visual-Design-Coordinator_JR1001"
        ),
        "description_html": (
            "<p>1-2 years of visual design experience.</p>"
        ),
        "first_published": "2026-07-20",
        "time_type": "Full time",
        "remote_type": "On-site",
        "country_codes": ["CN"],
        "detail_status": "ok",
    }
    job.update(overrides)
    return job


def raw_smartrecruiters_job(**overrides):
    job = {
        "source_job_id": "7440001001",
        "title": "Visual Design Coordinator",
        "location": "Beijing, Beijing, China",
        "url": (
            "https://jobs.smartrecruiters.com/"
            "ExampleStudio/7440001001-visual-design-coordinator"
        ),
        "description_html": (
            "<p>1-2 years of visual design experience.</p>"
        ),
        "first_published": "2026-07-27T12:00:00Z",
        "employment_label": "Full-time",
        "remote": False,
        "hybrid": True,
        "country_codes": ["CN"],
        "detail_status": "ok",
    }
    job.update(overrides)
    return job


class TextExtractionTests(unittest.TestCase):
    def test_extracts_text_without_retaining_markup(self):
        text = job_facts.html_to_text(
            "<h2>Requirements</h2><ul><li>Design &amp; illustration</li></ul>"
        )
        self.assertEqual(text, "Requirements\nDesign & illustration")
        self.assertNotIn("<li>", text)

    def test_extracts_greenhouse_entity_encoded_html(self):
        text = job_facts.html_to_text(
            "&amp;lt;p&amp;gt;3+ years of design experience."
            "&amp;lt;/p&amp;gt;"
        )
        self.assertEqual(text, "3+ years of design experience.")

    def test_ignores_script_and_style_content(self):
        text = job_facts.html_to_text(
            "<style>.role{display:none}</style>"
            "<script>window.fake='20 years of experience'</script>"
            "<p>Public role details.</p>"
        )
        self.assertEqual(text, "Public role details.")

    def test_bounds_untrusted_description_size(self):
        value = "<p>" + ("x" * (job_facts.MAX_DESCRIPTION_CHARS + 100)) + "</p>"
        text = job_facts.html_to_text(value)
        self.assertLessEqual(len(text), job_facts.MAX_DESCRIPTION_CHARS)


class FactInferenceTests(unittest.TestCase):
    def test_extracts_required_experience_range(self):
        self.assertEqual(
            job_facts.infer_experience(
                "Requirements\n3-5 years of relevant professional experience."
            ),
            {"min_years": 3, "max_years": 5, "explicit": True},
        )

    def test_ignores_preferred_experience(self):
        self.assertEqual(
            job_facts.infer_experience(
                "Nice to have: 5+ years of illustration experience."
            ),
            {"min_years": None, "max_years": None, "explicit": False},
        )

    def test_uses_strict_people_management_signals(self):
        self.assertEqual(
            job_facts.infer_people_management(
                "You will have 4 direct reports."
            ),
            "required",
        )
        self.assertEqual(
            job_facts.infer_people_management(
                "Lead cross-functional projects with partner teams."
            ),
            "unknown",
        )

    def test_parses_remote_country_and_region_scope(self):
        scope = job_facts.infer_remote_eligibility(
            "Remote, Canada; Remote, United Kingdom; Remote, APAC",
            "",
            "remote",
        )
        self.assertEqual(scope["scope"], "limited")
        self.assertEqual(scope["allowed_countries"], ["GB", "CA"])
        self.assertEqual(scope["allowed_regions"], ["APAC"])

    def test_remote_without_explicit_scope_stays_unknown(self):
        self.assertEqual(
            job_facts.infer_remote_eligibility("Remote", "", "remote"),
            {
                "scope": "unknown",
                "allowed_countries": [],
                "allowed_regions": [],
            },
        )

    def test_parses_beijing_as_a_public_place_fact(self):
        self.assertEqual(
            job_facts.parse_places("China, Beijing"),
            [
                {
                    "city": "Beijing",
                    "region": "Beijing",
                    "country_code": "CN",
                }
            ],
        )


class GreenhouseNormalizationTests(unittest.TestCase):
    def normalize(self, **overrides):
        return job_facts.normalize_greenhouse_job(
            COMPANY,
            raw_job(**overrides),
            first_seen_on="2026-07-28",
            observed_at=OBSERVED_AT,
        )

    def test_builds_schema_v1_public_metadata(self):
        job = self.normalize()
        self.assertEqual(job["schema_version"], 1)
        self.assertEqual(job["id"], "greenhouse:example-studio:1001")
        self.assertEqual(job["source"]["mode"], "automatic")
        self.assertEqual(job["work_arrangement"], "remote")
        self.assertEqual(
            job["remote_eligibility"]["allowed_countries"], ["US"]
        )
        self.assertEqual(
            job["experience"],
            {"min_years": 3, "max_years": None, "explicit": True},
        )
        self.assertEqual(job["requirements"]["portfolio"], "required")
        self.assertEqual(job["dates"]["published_on"], "2026-07-26")
        self.assertEqual(job["privacy"]["visibility"], "public_metadata")
        self.assertEqual(job["privacy"]["raw_description"], "not_stored")
        self.assertFalse(job["privacy"]["contains_candidate_data"])

    def test_never_returns_raw_description_or_contact_details(self):
        marker = "candidate@example.com"
        job = self.normalize(
            description_html=(
                "<p>Contact candidate@example.com.</p>"
                "<p>3+ years of design experience.</p>"
            )
        )
        serialized = json.dumps(job)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("description_html", serialized)
        self.assertNotIn("Contact", serialized)

    def test_rejects_non_https_or_credentialed_source_links(self):
        self.assertIsNone(self.normalize(url="http://example.com/jobs/1001"))
        self.assertIsNone(
            self.normalize(
                url="https://user:pass@example.com/jobs/1001"
            )
        )

    def test_unknown_is_not_converted_to_a_rejection_fact(self):
        job = self.normalize(
            title="Visual Designer",
            location="Remote",
            description_html="<p>Create visual assets.</p>",
        )
        self.assertEqual(job["remote_eligibility"]["scope"], "unknown")
        self.assertFalse(job["experience"]["explicit"])
        self.assertEqual(
            job["classification"]["people_management"], "unknown"
        )
        self.assertEqual(job["requirements"]["portfolio"], "not_mentioned")


class WorkdayNormalizationTests(unittest.TestCase):
    def normalize(self, **overrides):
        return job_facts.normalize_workday_job(
            COMPANY,
            raw_workday_job(**overrides),
            first_seen_on="2026-07-28",
            observed_at=OBSERVED_AT,
        )

    def test_uses_explicit_workday_metadata(self):
        job = self.normalize()
        self.assertEqual(job["id"], "workday:example-studio:jr1001")
        self.assertEqual(job["source"]["platform"], "workday")
        self.assertEqual(job["work_arrangement"], "onsite")
        self.assertEqual(job["employment_type"], "full_time")
        self.assertEqual(
            job["location"]["places"],
            [
                {
                    "city": "Beijing",
                    "region": "Beijing",
                    "country_code": "CN",
                }
            ],
        )
        self.assertEqual(
            job["experience"],
            {"min_years": 1, "max_years": 2, "explicit": True},
        )
        self.assertEqual(job["dates"]["published_on"], "2026-07-20")

    def test_remote_workday_country_is_limited_not_worldwide(self):
        job = self.normalize(
            location="Remote",
            remote_type="Remote",
            country_codes=["CN"],
        )
        self.assertEqual(job["work_arrangement"], "remote")
        self.assertEqual(
            job["remote_eligibility"],
            {
                "scope": "limited",
                "allowed_countries": ["CN"],
                "allowed_regions": [],
            },
        )

    def test_never_serializes_workday_description(self):
        marker = "private-contact@example.com"
        job = self.normalize(
            description_html=(
                f"<p>{marker}</p>"
                "<p>2+ years of visual design experience.</p>"
            )
        )
        serialized = json.dumps(job)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("description_html", serialized)

    def test_unsafe_source_identifier_is_hashed_for_record_id(self):
        job = self.normalize(source_job_id="Job Req / 1001")
        self.assertRegex(
            job["id"],
            r"^workday:example-studio:[a-f0-9]{24}$",
        )
        self.assertEqual(
            job["source"]["source_job_id"], "Job Req / 1001"
        )


class SmartRecruitersNormalizationTests(unittest.TestCase):
    def normalize(self, **overrides):
        return job_facts.normalize_smartrecruiters_job(
            COMPANY,
            raw_smartrecruiters_job(**overrides),
            first_seen_on="2026-07-28",
            observed_at=OBSERVED_AT,
        )

    def test_uses_explicit_smartrecruiters_metadata(self):
        job = self.normalize()
        self.assertEqual(
            job["id"],
            "smartrecruiters:example-studio:7440001001",
        )
        self.assertEqual(
            job["source"]["platform"], "smartrecruiters"
        )
        self.assertEqual(job["work_arrangement"], "hybrid")
        self.assertEqual(job["employment_type"], "full_time")
        self.assertEqual(
            job["experience"],
            {"min_years": 1, "max_years": 2, "explicit": True},
        )
        self.assertEqual(job["dates"]["published_on"], "2026-07-27")

    def test_remote_country_is_limited_not_worldwide(self):
        job = self.normalize(
            location="Tokyo, Japan",
            remote=True,
            hybrid=False,
            country_codes=["JP"],
        )
        self.assertEqual(job["work_arrangement"], "remote")
        self.assertEqual(
            job["remote_eligibility"],
            {
                "scope": "limited",
                "allowed_countries": ["JP"],
                "allowed_regions": [],
            },
        )

    def test_never_serializes_smartrecruiters_description(self):
        marker = "private-contact@example.com"
        job = self.normalize(
            description_html=(
                f"<p>{marker}</p>"
                "<p>2+ years of visual design experience.</p>"
            )
        )
        serialized = json.dumps(job)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("description_html", serialized)

    def test_missing_remote_metadata_stays_unknown(self):
        job = self.normalize(
            location="Remote",
            remote=None,
            hybrid=None,
            country_codes=[],
            description_html="<p>Create visual assets.</p>",
        )
        self.assertEqual(job["work_arrangement"], "remote")
        self.assertEqual(job["remote_eligibility"]["scope"], "unknown")


if __name__ == "__main__":
    unittest.main()
