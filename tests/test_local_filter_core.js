"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const filter = require("../docs/local-filter-core.js");

function makeJob(overrides = {}) {
  const job = {
    schema_version: 1,
    id: "boss:example-1",
    source: {
      platform: "boss",
      mode: "assisted",
      source_job_id: "example-1",
      url: "https://www.zhipin.com/job_detail/example-1.html",
    },
    title: "平面插画助理",
    company: { id: "example-studio", name: "示例工作室" },
    location: {
      raw: "北京·朝阳区",
      places: [{ city: "Beijing", region: "Beijing", country_code: "CN" }],
    },
    work_arrangement: "onsite",
    remote_eligibility: {
      scope: "not_applicable",
      allowed_countries: [],
      allowed_regions: [],
    },
    employment_type: "full_time",
    compensation: {
      disclosed: false,
      currency: null,
      amount_min: null,
      amount_max: null,
      period: "unknown",
      annual_pay_periods: null,
    },
    experience: { min_years: 0, max_years: 1, explicit: true },
    requirements: { portfolio: "required" },
    classification: {
      role_families: ["illustration"],
      seniority: "junior",
      people_management: "not_required",
    },
    summary: "协助完成平面插画与视觉物料。",
    dates: {
      published_on: null,
      first_seen_on: "2026-07-28",
      captured_at: "2026-07-28T02:30:00Z",
    },
    provenance: {
      capture_method: "manual_entry",
      evidence: [],
    },
    privacy: {
      visibility: "local_only",
      raw_description: "not_stored",
      contains_candidate_data: false,
    },
  };
  return Object.assign(job, overrides);
}

function remoteJob(remoteEligibility) {
  return makeJob({
    id: "linkedin:remote-1",
    source: {
      platform: "linkedin",
      mode: "assisted",
      source_job_id: "remote-1",
      url: "https://www.linkedin.com/jobs/view/remote-1/",
    },
    location: { raw: "Remote", places: [] },
    work_arrangement: "remote",
    remote_eligibility: remoteEligibility,
  });
}

function publicJob(overrides = {}) {
  return makeJob({
    id: "greenhouse:example-studio:public-1",
    source: {
      platform: "greenhouse",
      mode: "automatic",
      source_job_id: "public-1",
      url: "https://job-boards.greenhouse.io/example/jobs/public-1",
    },
    provenance: {
      capture_method: "public_endpoint",
      evidence: [],
    },
    privacy: {
      visibility: "public_metadata",
      raw_description: "not_stored",
      contains_candidate_data: false,
    },
    ...overrides,
  });
}

function reasonCodes(result) {
  return result.reasons.map((reason) => reason.code);
}

test("default preferences remain neutral", () => {
  const preferences = filter.normalizePreferences();
  assert.deepEqual(preferences.allowedWorkArrangements, [
    "onsite",
    "hybrid",
    "remote",
  ]);
  assert.deepEqual(preferences.onsiteCities, []);
  assert.equal(preferences.remoteCountryCode, null);
  assert.deepEqual(preferences.acceptedEmploymentTypes, []);
  assert.equal(preferences.preferredMaxExperienceYears, null);
  assert.equal(preferences.stretchMaxExperienceYears, null);
  assert.equal(preferences.excludePeopleManagement, false);
});

test("Beijing/CN preset is generic and does not contain experience limits", () => {
  const preset = filter.getPreset("beijing-cn");
  assert.deepEqual(preset.onsiteCities, ["北京", "Beijing"]);
  assert.equal(preset.remoteCountryCode, "CN");
  assert.equal(preset.preferredMaxExperienceYears, null);
  assert.equal(preset.stretchMaxExperienceYears, null);
});

test("creates a safe normalized local-only job from manual fields", () => {
  const job = filter.createManualJob(
    {
      source: "boss",
      url: "https://www.zhipin.com/job_detail/manual-1.html",
      title: "插画助理",
      company: "示例工作室",
      locationRaw: "北京·朝阳区",
      city: "Beijing",
      countryCode: "cn",
      workArrangement: "hybrid",
      remoteScope: "limited",
      allowedCountries: ["cn"],
      employmentType: "full_time",
      experienceMinYears: "0",
      experienceMaxYears: "1",
      peopleManagement: "not_required",
      roleFamilies: ["illustration"],
    },
    "2026-07-28T02:30:00Z",
  );
  assert.equal(filter.validateNormalizedJob(job).valid, true);
  assert.equal(job.privacy.visibility, "local_only");
  assert.equal(job.privacy.contains_candidate_data, false);
  assert.equal(job.remote_eligibility.allowed_countries[0], "CN");
  assert.equal(job.dates.captured_at, "2026-07-28T02:30:00.000Z");
});

test("manual creation rejects sensitive fields and contact details", () => {
  const base = {
    source: "linkedin",
    url: "https://www.linkedin.com/jobs/view/manual-1/",
    title: "Junior Illustrator",
    company: "Example Studio",
    locationRaw: "Remote",
    workArrangement: "remote",
    remoteScope: "unknown",
  };
  assert.throws(
    () => filter.createManualJob({ ...base, candidate_email: "me@example.com" }),
    /sensitive field/,
  );
  assert.throws(
    () => filter.createManualJob({ ...base, summary: "Call +61 412 345 678" }),
    /phone number/,
  );
});

test("normalized file records reject unsupported top-level fields", () => {
  const result = filter.validateNormalizedJob({
    ...makeJob(),
    private_notes: "do not retain this",
  });
  assert.equal(result.valid, false);
  assert.ok(
    result.errors.some((error) =>
      error.includes("unsupported fields: private_notes"),
    ),
  );
});

test("reads a bounded public automatic snapshot", () => {
  const snapshot = filter.readPublicSnapshot({
    schema_version: 1,
    updated: "2026-07-28",
    jobs: [publicJob()],
  });
  assert.equal(snapshot.updated, "2026-07-28");
  assert.equal(snapshot.jobs.length, 1);
  assert.equal(snapshot.jobs[0].privacy.visibility, "public_metadata");
});

test("rejects local or assisted records in the public snapshot", () => {
  assert.throws(
    () =>
      filter.readPublicSnapshot({
        schema_version: 1,
        updated: "2026-07-28",
        jobs: [makeJob()],
      }),
    /not public automatic metadata/,
  );
  assert.throws(
    () =>
      filter.readPublicSnapshot({
        schema_version: 1,
        updated: "2026-07-28",
        jobs: [
          publicJob({
            source: {
              platform: "custom",
              mode: "automatic",
              source_job_id: "public-1",
              url: "https://example.com/jobs/public-1",
            },
          }),
        ],
      }),
    /not public automatic metadata/,
  );
});

test("rejects malformed or oversized public snapshots", () => {
  assert.throws(
    () =>
      filter.readPublicSnapshot({
        schema_version: 1,
        updated: "2026-02-31",
        jobs: [],
      }),
    /ISO date/,
  );
  assert.throws(
    () =>
      filter.readPublicSnapshot(
        {
          schema_version: 1,
          updated: "2026-07-28",
          jobs: [publicJob(), publicJob({ id: "greenhouse:example:2" })],
        },
        1,
      ),
    /job limit/,
  );
  assert.throws(
    () =>
      filter.readPublicSnapshot({
        schema_version: 1,
        updated: "2026-07-28",
        jobs: [],
        private_preferences: {},
      }),
    /unsupported fields/,
  );
});

test("normalizes bounded personal focus directions", () => {
  const directions = filter.normalizeFocusDirections([
    {
      id: "illustration",
      name: "插画／平面设计",
      keywords: ["Illustrator", "illustrator", "平面设计"],
      active: true,
    },
  ]);
  assert.equal(directions.length, 1);
  assert.deepEqual(directions[0].keywords, ["Illustrator", "平面设计"]);
  assert.equal(directions[0].active, true);

  assert.throws(
    () =>
      filter.normalizeFocusDirection({
        id: "empty",
        name: "空方向",
        keywords: [],
      }),
    /needs 1 to 20 keywords/,
  );
  assert.throws(
    () =>
      filter.normalizeFocusDirections(
        Array.from({ length: 31 }, (_value, index) => ({
          id: `focus-${index}`,
          name: `Direction ${index}`,
          keywords: [`keyword-${index}`],
        })),
      ),
    /cannot exceed 30/,
  );
});

test("matches focus directions against transparent job fields", () => {
  const job = makeJob({
    title: "Junior Visual Artist",
    company: { id: "pet-studio", name: "Pet Story Studio" },
    summary: "Create flat illustration assets.",
  });
  const directions = [
    {
      id: "illustration",
      name: "插画",
      keywords: ["illustration"],
      active: true,
    },
    {
      id: "pets",
      name: "宠物内容",
      keywords: ["pet story"],
      active: true,
    },
    {
      id: "engineering",
      name: "工程",
      keywords: ["backend"],
      active: true,
    },
  ];
  assert.deepEqual(
    filter
      .matchingFocusDirections(job, directions)
      .map((direction) => direction.id),
    ["illustration", "pets"],
  );
});

test("focus directions filter the local view without changing job outcomes", () => {
  const jobs = [
    makeJob({ id: "boss:illustration", title: "插画助理" }),
    makeJob({
      id: "boss:operations",
      title: "运营助理",
      summary: "协助安排项目进度。",
      classification: {
        role_families: ["operations"],
        seniority: "junior",
        people_management: "not_required",
      },
    }),
  ];
  const active = [
    {
      id: "illustration",
      name: "插画",
      keywords: ["插画"],
      active: true,
    },
  ];
  assert.deepEqual(
    filter.filterJobsByFocus(jobs, active).map((job) => job.id),
    ["boss:illustration"],
  );
  assert.deepEqual(
    filter
      .filterJobsByFocus(jobs, [{ ...active[0], active: false }])
      .map((job) => job.id),
    ["boss:illustration", "boss:operations"],
  );
  assert.equal(filter.evaluateJob(jobs[0], {}).outcome, "A");
});

test("allows an explicitly matching Beijing onsite job", () => {
  const result = filter.evaluateJob(makeJob(), filter.getPreset("beijing-cn"));
  assert.equal(result.valid, true);
  assert.equal(result.outcome, "A");
});

test("rejects an explicitly different onsite city", () => {
  const job = makeJob({
    location: {
      raw: "上海",
      places: [{ city: "Shanghai", region: "Shanghai", country_code: "CN" }],
    },
  });
  const result = filter.evaluateJob(job, filter.getPreset("beijing-cn"));
  assert.equal(result.outcome, "X");
  assert.ok(reasonCodes(result).includes("onsite_city_excluded"));
});

test("keeps a missing onsite city for human review", () => {
  const job = makeJob({
    location: { raw: "China", places: [] },
  });
  const result = filter.evaluateJob(job, filter.getPreset("beijing-cn"));
  assert.equal(result.outcome, "C");
  assert.ok(reasonCodes(result).includes("onsite_city_unknown"));
});

test("allows worldwide remote work for a CN preference", () => {
  const job = remoteJob({
    scope: "worldwide",
    allowed_countries: [],
    allowed_regions: [],
  });
  assert.equal(
    filter.evaluateJob(job, filter.getPreset("beijing-cn")).outcome,
    "A",
  );
});

test("allows remote work that explicitly includes CN", () => {
  const job = remoteJob({
    scope: "limited",
    allowed_countries: ["CN"],
    allowed_regions: [],
  });
  assert.equal(
    filter.evaluateJob(job, filter.getPreset("beijing-cn")).outcome,
    "A",
  );
});

test("rejects remote work whose explicit country list excludes CN", () => {
  const job = remoteJob({
    scope: "limited",
    allowed_countries: ["US", "CA"],
    allowed_regions: [],
  });
  const result = filter.evaluateJob(job, filter.getPreset("beijing-cn"));
  assert.equal(result.outcome, "X");
  assert.ok(reasonCodes(result).includes("remote_country_excluded"));
});

test("keeps mixed country and broad-region eligibility for review", () => {
  const job = remoteJob({
    scope: "limited",
    allowed_countries: ["US", "CA"],
    allowed_regions: ["APAC"],
  });
  const result = filter.evaluateJob(job, filter.getPreset("beijing-cn"));
  assert.equal(result.outcome, "C");
  assert.ok(reasonCodes(result).includes("remote_region_needs_review"));
});

test("does not treat unknown remote eligibility as rejection", () => {
  const job = remoteJob({
    scope: "unknown",
    allowed_countries: [],
    allowed_regions: [],
  });
  const result = filter.evaluateJob(job, filter.getPreset("beijing-cn"));
  assert.equal(result.outcome, "C");
  assert.ok(reasonCodes(result).includes("remote_eligibility_unknown"));
});

test("classifies experience as A, B, or X against explicit thresholds", () => {
  const preferences = {
    preferredMaxExperienceYears: 1,
    stretchMaxExperienceYears: 2,
  };
  const ideal = filter.evaluateJob(makeJob(), preferences);
  const stretch = filter.evaluateJob(
    makeJob({ experience: { min_years: 2, max_years: 3, explicit: true } }),
    preferences,
  );
  const blocked = filter.evaluateJob(
    makeJob({ experience: { min_years: 3, max_years: 5, explicit: true } }),
    preferences,
  );
  assert.equal(ideal.outcome, "A");
  assert.equal(stretch.outcome, "B");
  assert.equal(blocked.outcome, "X");
});

test("keeps unknown experience for human review when a limit is active", () => {
  const job = makeJob({
    experience: { min_years: null, max_years: null, explicit: false },
  });
  const result = filter.evaluateJob(job, {
    preferredMaxExperienceYears: 1,
    stretchMaxExperienceYears: 2,
  });
  assert.equal(result.outcome, "C");
  assert.ok(reasonCodes(result).includes("experience_unknown"));
});

test("uses explicit management requirements as a blocker, not title guesses", () => {
  const required = makeJob({
    classification: {
      role_families: ["illustration"],
      seniority: "junior",
      people_management: "required",
    },
  });
  const unknown = makeJob({
    classification: {
      role_families: ["illustration"],
      seniority: "junior",
      people_management: "unknown",
    },
  });
  assert.equal(
    filter.evaluateJob(required, { excludePeopleManagement: true }).outcome,
    "X",
  );
  assert.equal(
    filter.evaluateJob(unknown, { excludePeopleManagement: true }).outcome,
    "C",
  );
});

test("rejects invalid privacy state before classification", () => {
  const job = makeJob({
    privacy: {
      visibility: "public_metadata",
      raw_description: "not_stored",
      contains_candidate_data: false,
    },
  });
  const result = filter.evaluateJob(job, {});
  assert.equal(result.valid, false);
  assert.equal(result.outcome, null);
  assert.ok(result.errors.includes("BOSS and LinkedIn records must remain local_only"));
});

test("rejects credentialed or non-official assisted-source URLs", () => {
  for (const url of [
    "https://user:pass@www.zhipin.com/job_detail/example.html",
    "https://example.com/job",
    "https://www.zhipin.com/job_detail/example.html?access_token=private",
  ]) {
    const job = makeJob({
      source: {
        platform: "boss",
        mode: "assisted",
        source_job_id: "example-1",
        url,
      },
    });
    assert.equal(filter.validateNormalizedJob(job).valid, false);
  }
});

test("hides only X outcomes by default", () => {
  const preferences = {
    preferredMaxExperienceYears: 1,
    stretchMaxExperienceYears: 2,
  };
  const jobs = [
    makeJob({ id: "boss:a" }),
    makeJob({
      id: "boss:b",
      experience: { min_years: 2, max_years: 3, explicit: true },
    }),
    makeJob({
      id: "boss:c",
      experience: { min_years: null, max_years: null, explicit: false },
    }),
    makeJob({
      id: "boss:x",
      experience: { min_years: 5, max_years: 8, explicit: true },
    }),
  ];
  const evaluation = filter.evaluateJobs(jobs, preferences);
  assert.deepEqual(evaluation.summary, {
    A: 1,
    B: 1,
    C: 1,
    X: 1,
    invalid: 0,
  });
  assert.deepEqual(
    filter.visibleResults(evaluation).map((result) => result.outcome),
    ["A", "B", "C"],
  );
  assert.equal(filter.visibleResults(evaluation, { showX: true }).length, 4);
});
