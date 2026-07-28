import datetime as dt
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import import_jobs


NOW = dt.datetime(2026, 7, 28, 2, 30, tzinfo=dt.timezone.utc)
REGISTRY = {
    "boss": {
        "id": "boss",
        "mode": "assisted",
        "input_methods": [
            "manual_entry",
            "local_file_import",
            "user_received_job_alert",
        ],
    },
    "linkedin": {
        "id": "linkedin",
        "mode": "assisted",
        "input_methods": [
            "manual_entry",
            "local_file_import",
            "user_received_job_alert",
        ],
    },
}


def boss_record():
    return {
        "source": "boss",
        "capture_method": "manual_entry",
        "url": "https://www.zhipin.com/job_detail/example.html",
        "title": "平面插画助理",
        "company": "示例工作室",
        "location_raw": "北京·朝阳区",
        "city": "Beijing",
        "region": "Beijing",
        "country_code": "CN",
        "work_arrangement": "hybrid",
        "remote_scope": "limited",
        "allowed_countries": ["CN"],
        "employment_type": "full_time",
        "currency": "CNY",
        "salary_min": 8000,
        "salary_max": 12000,
        "pay_period": "month",
        "annual_pay_periods": 13,
        "experience_min_years": 0,
        "experience_max_years": 1,
        "portfolio": "required",
        "role_families": ["illustration", "graphic-design"],
        "seniority": "junior",
        "people_management": "not_required",
        "summary": "协助完成平面插画与视觉物料制作。",
    }


class NormalizePayloadTests(unittest.TestCase):
    def normalize(self, payload):
        return import_jobs.normalize_payload(
            payload,
            registry=REGISTRY,
            observed_at=NOW,
        )

    def test_normalizes_boss_record_as_local_only(self):
        jobs = self.normalize([boss_record()])
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["source"]["platform"], "boss")
        self.assertEqual(job["source"]["mode"], "assisted")
        self.assertEqual(job["privacy"]["visibility"], "local_only")
        self.assertFalse(job["privacy"]["contains_candidate_data"])
        self.assertEqual(job["remote_eligibility"]["allowed_countries"], ["CN"])
        self.assertEqual(job["compensation"]["annual_pay_periods"], 13)
        self.assertTrue(job["experience"]["explicit"])

    def test_normalizes_linkedin_alert_for_remote_china(self):
        record = {
            "source": "linkedin",
            "capture_method": "user_received_job_alert",
            "source_job_id": "example-1",
            "url": "https://www.linkedin.com/jobs/view/example-1/",
            "title": "Junior Community Illustrator",
            "company": "Example Community",
            "location_raw": "Remote — China",
            "work_arrangement": "remote",
            "remote_scope": "limited",
            "allowed_countries": ["CN"],
            "employment_type": "contract",
            "portfolio": "preferred",
            "role_families": ["illustration"],
            "seniority": "junior",
        }
        job = self.normalize({"jobs": [record]})[0]
        self.assertEqual(
            job["provenance"]["capture_method"], "user_received_job_alert"
        )
        self.assertEqual(job["remote_eligibility"]["scope"], "limited")
        self.assertEqual(job["compensation"]["disclosed"], False)

    def test_rejects_cookie_or_token_fields(self):
        for field in ("cookie", "access_token", "resume_text"):
            with self.subTest(field=field):
                record = boss_record()
                record[field] = "private"
                with self.assertRaises(import_jobs.ImportValidationError):
                    self.normalize([record])

    def test_rejects_url_credentials_and_sensitive_query(self):
        record = boss_record()
        record["url"] = "https://user:pass@www.zhipin.com/job_detail/example.html"
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record])

        record = boss_record()
        record["url"] = (
            "https://www.zhipin.com/job_detail/example.html?access_token=private"
        )
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record])

    def test_rejects_wrong_platform_domain(self):
        record = boss_record()
        record["url"] = "https://example.com/job"
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record])

    def test_rejects_contact_details_in_text_and_url(self):
        cases = [
            ("summary", "Contact candidate@example.com"),
            ("summary", "联系电话 13812345678"),
            ("summary", "Call +61 412 345 678"),
            (
                "url",
                "https://www.zhipin.com/job_detail/candidate@example.com.html",
            ),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                record = boss_record()
                record[field] = value
                with self.assertRaises(import_jobs.ImportValidationError):
                    self.normalize([record])

    def test_rejects_limited_remote_without_regions(self):
        record = boss_record()
        record["allowed_countries"] = []
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record])

    def test_rejects_inverted_ranges(self):
        record = boss_record()
        record["salary_min"] = 12000
        record["salary_max"] = 8000
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record])

        record = boss_record()
        record["experience_min_years"] = 3
        record["experience_max_years"] = 1
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record])

    def test_deduplicates_exact_records_and_rejects_conflicts(self):
        record = boss_record()
        self.assertEqual(len(self.normalize([record, deepcopy(record)])), 1)

        conflict = deepcopy(record)
        conflict["title"] = "不同职位名称"
        with self.assertRaises(import_jobs.ImportValidationError):
            self.normalize([record, conflict])


class OutputSafetyTests(unittest.TestCase):
    def test_rejects_output_outside_private_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "jobs.json"
            with self.assertRaises(import_jobs.ImportValidationError):
                import_jobs.validate_output_path(outside)

    def test_write_requires_force_to_replace(self):
        jobs = import_jobs.normalize_payload(
            [boss_record()],
            registry=REGISTRY,
            observed_at=NOW,
        )
        private_root = import_jobs.ROOT / "local"
        private_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=private_root) as directory:
            output = Path(directory) / "jobs.json"
            import_jobs.write_private_json(output, jobs, force=False)
            with self.assertRaises(import_jobs.ImportValidationError):
                import_jobs.write_private_json(output, jobs, force=False)
            import_jobs.write_private_json(output, jobs, force=True)
            stored = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stored, jobs)


if __name__ == "__main__":
    unittest.main()
