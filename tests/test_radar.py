import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import radar


class UrlSafetyTests(unittest.TestCase):
    def test_accepts_public_http_urls(self):
        self.assertEqual(
            radar.safe_http_url(" https://example.com/jobs/1 "),
            "https://example.com/jobs/1",
        )
        self.assertEqual(
            radar.safe_http_url("http://example.com/jobs/1"),
            "http://example.com/jobs/1",
        )

    def test_rejects_unsafe_or_credentialed_urls(self):
        for value in (
            None,
            "",
            "javascript:alert(1)",
            "data:text/html,hello",
            "//example.com/jobs/1",
            "https://user:pass@example.com/jobs/1",
            "https:///jobs/1",
        ):
            with self.subTest(value=value):
                self.assertEqual(radar.safe_http_url(value), "")

    def test_http_json_rejects_bad_url_before_network(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError):
                radar.http_json("file:///tmp/jobs.json")
        urlopen.assert_not_called()


class CollectionTests(unittest.TestCase):
    def test_greenhouse_requests_public_content_without_application_fields(self):
        response = {
            "jobs": [
                {
                    "id": 1001,
                    "title": "Visual Designer",
                    "location": {"name": "Remote, US"},
                    "absolute_url": (
                        "https://job-boards.greenhouse.io/example/jobs/1001"
                    ),
                    "content": "<p>Public description.</p>",
                    "metadata": [],
                }
            ]
        }
        with mock.patch.object(
            radar, "http_json", return_value=response
        ) as http_json:
            jobs = radar.fetch_greenhouse({"slug": "example"})

        http_json.assert_called_once_with(
            "https://boards-api.greenhouse.io/v1/boards/example/jobs"
            "?content=true"
        )
        self.assertEqual(jobs[0]["source_job_id"], "1001")
        self.assertEqual(
            jobs[0]["description_html"], "<p>Public description.</p>"
        )

    def test_workday_prefilters_before_requesting_details(self):
        company = {
            "id": "example",
            "name": "Example",
            "track": "Creative",
            "ats": "workday",
            "location_keywords": ["Beijing"],
            "workday": {
                "host": "example.wd5.myworkdayjobs.com",
                "tenant": "example",
                "site": "External",
            },
        }
        listing = {
            "total": 2,
            "jobPostings": [
                {
                    "title": "Visual Designer",
                    "locationsText": "China, Beijing",
                    "externalPath": (
                        "/job/China-Beijing/Visual-Designer_JR1001"
                    ),
                },
                {
                    "title": "Visual Designer",
                    "locationsText": "China, Shanghai",
                    "externalPath": (
                        "/job/China-Shanghai/Visual-Designer_JR1002"
                    ),
                },
            ],
        }
        detail = {
            "jobPostingInfo": {
                "canApply": True,
                "jobReqId": "JR1001",
                "title": "Visual Designer",
                "location": "China, Beijing",
                "externalUrl": (
                    "https://example.wd5.myworkdayjobs.com/External/"
                    "job/China-Beijing/Visual-Designer_JR1001"
                ),
                "jobDescription": "<p>1+ years of design experience.</p>",
                "startDate": "2026-07-20",
                "timeType": "Full time",
                "remoteType": "On-site",
                "jobRequisitionLocation": {
                    "country": {"alpha2Code": "CN"}
                },
            }
        }

        def fake_http_json(url, payload=None, timeout=25):
            if url.endswith("/jobs"):
                return listing
            return detail

        with mock.patch.object(
            radar, "http_json", side_effect=fake_http_json
        ) as http_json:
            jobs = radar.fetch_workday(company)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source_job_id"], "JR1001")
        self.assertEqual(jobs[0]["detail_status"], "ok")
        self.assertEqual(jobs[0]["country_codes"], ["CN"])
        self.assertEqual(http_json.call_count, 2)

    def test_workday_detail_failure_degrades_to_public_summary(self):
        company = {
            "id": "example",
            "name": "Example",
            "track": "Creative",
            "ats": "workday",
            "workday": {
                "host": "example.wd5.myworkdayjobs.com",
                "tenant": "example",
                "site": "External",
            },
        }
        listing = {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Visual Designer",
                    "locationsText": "China, Beijing",
                    "externalPath": (
                        "/job/China-Beijing/Visual-Designer_JR1001"
                    ),
                }
            ],
        }

        def fake_http_json(url, payload=None, timeout=25):
            if url.endswith("/jobs"):
                return listing
            raise TimeoutError("detail unavailable")

        with mock.patch.object(
            radar, "http_json", side_effect=fake_http_json
        ):
            jobs = radar.fetch_workday(company)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["detail_status"], "unavailable")
        self.assertEqual(jobs[0]["description_html"], "")

    def test_normalizes_only_public_job_fields(self):
        job = radar.normalize_fetched_job(
            {
                "title": "  Junior Illustrator  ",
                "location": "  Beijing  ",
                "url": " https://example.com/jobs/1 ",
                "description": "must not pass through this boundary",
            }
        )
        self.assertEqual(
            job,
            {
                "title": "Junior Illustrator",
                "location": "Beijing",
                "url": "https://example.com/jobs/1",
            },
        )

    def test_rejects_incomplete_or_unsafe_jobs(self):
        self.assertIsNone(
            radar.normalize_fetched_job(
                {
                    "title": "Illustrator",
                    "location": "Beijing",
                    "url": "javascript:alert(1)",
                }
            )
        )
        self.assertIsNone(
            radar.normalize_fetched_job(
                {
                    "title": "",
                    "location": "Beijing",
                    "url": "https://example.com/jobs/1",
                }
            )
        )

    def test_neutral_collection_scope_keeps_valid_job(self):
        job = {
            "title": "Illustrator",
            "location": "Shanghai",
            "url": "https://example.com/jobs/1",
        }
        self.assertTrue(radar.keep(job, {}))

    def test_legacy_collection_scope_is_not_fit_evaluation(self):
        job = {
            "title": "Data Analyst",
            "location": "Shanghai",
            "url": "https://example.com/jobs/1",
        }
        self.assertFalse(
            radar.keep(
                job,
                {
                    "title_exclude": ["Data"],
                    "location_keywords": ["Beijing"],
                },
            )
        )

    def test_title_classification_is_only_a_signal(self):
        self.assertEqual(radar.seniority("Graduate Illustrator"), 0)
        self.assertEqual(radar.seniority("Marketing Manager"), 2)
        self.assertEqual(radar.seniority("AI Transformation Owner, CRO"), 1)
        self.assertEqual(radar.is_tech("Backend Engineer"), 1)
        self.assertEqual(radar.is_tech("Illustrator"), 0)


class RenderTests(unittest.TestCase):
    def test_render_drops_unsafe_links_and_copies_source_template(self):
        jobs = [
            {
                "company": "Example Studio",
                "title": "Junior Illustrator",
                "location": "Beijing",
                "url": "https://example.com/jobs/1",
                "track": "Creative",
                "first_seen": "2026-07-28",
            },
            {
                "company": "Unsafe",
                "title": "Unsafe link",
                "location": "Remote",
                "url": "javascript:alert(1)",
                "track": "Creative",
                "first_seen": "2026-07-28",
            },
        ]
        config = {"companies": [{"track": "Creative"}]}

        with tempfile.TemporaryDirectory() as directory:
            docs = os.path.join(directory, "docs")
            with open(
                os.path.join(directory, "template.html"),
                "w",
                encoding="utf-8",
            ) as output:
                output.write("<p>generated from source</p>")

            with mock.patch.multiple(
                radar,
                ROOT=directory,
                DOCS=docs,
                TODAY="2026-07-28",
            ):
                radar.render(jobs, [], config)

            with open(
                os.path.join(docs, "jobs.js"), encoding="utf-8"
            ) as source:
                generated = source.read()
            meta_text, jobs_text = generated.removeprefix(
                "window.META="
            ).split(";window.JOBS=", 1)
            meta = json.loads(meta_text)
            public_jobs = json.loads(jobs_text.removesuffix(";"))

            self.assertEqual(meta["total"], 1)
            self.assertEqual(len(public_jobs), 1)
            self.assertEqual(
                public_jobs[0]["u"], "https://example.com/jobs/1"
            )
            with open(
                os.path.join(docs, "index.html"), encoding="utf-8"
            ) as source:
                self.assertEqual(source.read(), "<p>generated from source</p>")

    def test_main_writes_greenhouse_schema_without_raw_description(self):
        fetched = [
            {
                "source_job_id": "1001",
                "title": "Junior Visual Designer",
                "location": "Remote, United States",
                "url": (
                    "https://job-boards.greenhouse.io/example/jobs/1001"
                ),
                "description_html": (
                    "<p>3+ years of visual design experience.</p>"
                    "<p>candidate@example.com</p>"
                ),
                "metadata": [],
                "first_published": "2026-07-26T12:00:00Z",
            }
        ]
        config = {
            "companies": [
                {
                    "id": "example",
                    "name": "Example Studio",
                    "track": "Creative",
                    "ats": "greenhouse",
                    "slug": "example",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as directory:
            docs = os.path.join(directory, "docs")
            data = os.path.join(directory, "data")
            os.makedirs(data)
            with open(
                os.path.join(directory, "companies.json"),
                "w",
                encoding="utf-8",
            ) as output:
                json.dump(config, output)
            with open(
                os.path.join(directory, "template.html"),
                "w",
                encoding="utf-8",
            ) as output:
                output.write("<p>template</p>")

            with (
                mock.patch.multiple(
                    radar,
                    ROOT=directory,
                    DOCS=docs,
                    DATA_PATH=os.path.join(data, "jobs.json"),
                    NORMALIZED_DATA_PATH=os.path.join(
                        data, "jobs.normalized.json"
                    ),
                    TODAY="2026-07-28",
                ),
                mock.patch.dict(
                    radar.FETCHERS,
                    {"greenhouse": lambda company: fetched},
                ),
            ):
                radar.main()

            with open(
                os.path.join(data, "jobs.normalized.json"),
                encoding="utf-8",
            ) as source:
                normalized = json.load(source)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["source"]["platform"], "greenhouse")
        serialized = json.dumps(normalized)
        self.assertNotIn("candidate@example.com", serialized)
        self.assertNotIn("description_html", serialized)


class PublicPageTests(unittest.TestCase):
    def test_public_template_has_neutral_safe_defaults(self):
        with open(
            os.path.join(ROOT, "template.html"), encoding="utf-8"
        ) as source:
            template = source.read()

        self.assertIn(
            'hideSenior=false,hideTech=false,earlyOnly=false', template
        )
        self.assertIn("connect-src 'none'", template)
        self.assertIn('name="referrer" content="no-referrer"', template)
        self.assertIn("早期标题信号", template)
        self.assertNotIn("早期友好", template)
        self.assertNotIn("fonts.googleapis.com", template)
        self.assertNotIn("｜Ciel｜", template)

    def test_public_readme_describes_privacy_boundary(self):
        with open(
            os.path.join(ROOT, "README.md"), encoding="utf-8"
        ) as source:
            readme = source.read()

        self.assertIn("不会自动投递", readme)
        self.assertIn("未知信息不能作为拒绝依据", readme)
        self.assertNotIn("给 Dawn 的私人职位雷达", readme)
        self.assertNotIn("维护：Ciel", readme)


if __name__ == "__main__":
    unittest.main()
