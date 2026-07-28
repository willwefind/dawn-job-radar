(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.JobRadarLocalFilter = Object.freeze(api);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const OUTCOME_PRIORITY = Object.freeze({ A: 0, B: 1, C: 2, X: 3 });
  const WORK_ARRANGEMENTS = new Set(["onsite", "hybrid", "remote", "unknown"]);
  const REMOTE_SCOPES = new Set([
    "worldwide",
    "limited",
    "unknown",
    "not_applicable",
  ]);
  const EMPLOYMENT_TYPES = new Set([
    "full_time",
    "part_time",
    "contract",
    "temporary",
    "internship",
    "freelance",
    "unknown",
  ]);
  const MANAGEMENT_VALUES = new Set([
    "required",
    "not_required",
    "unknown",
  ]);
  const AUTOMATIC_PUBLIC_PLATFORMS = new Set([
    "greenhouse",
    "smartrecruiters",
    "workday",
  ]);
  const ASSISTED_PLATFORM_DOMAINS = Object.freeze({
    boss: "zhipin.com",
    linkedin: "linkedin.com",
  });
  const SENSITIVE_QUERY_PARTS = [
    "access_token",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
  ];
  const SENSITIVE_KEY_PARTS = [
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
  ];
  const EMAIL_PATTERN = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;
  const PHONE_PATTERNS = [
    /(^|[^\d])1[3-9]\d{9}([^\d]|$)/,
    /(^|[^\w])\+\d[\d\s().-]{6,}\d([^\w]|$)/,
  ];
  const TOP_LEVEL_KEYS = new Set([
    "schema_version",
    "id",
    "source",
    "title",
    "company",
    "location",
    "work_arrangement",
    "remote_eligibility",
    "employment_type",
    "compensation",
    "experience",
    "requirements",
    "classification",
    "summary",
    "dates",
    "provenance",
    "privacy",
  ]);

  const DEFAULT_PREFERENCES = Object.freeze({
    allowedWorkArrangements: Object.freeze(["onsite", "hybrid", "remote"]),
    onsiteCities: Object.freeze([]),
    remoteCountryCode: null,
    acceptedEmploymentTypes: Object.freeze([]),
    preferredMaxExperienceYears: null,
    stretchMaxExperienceYears: null,
    excludePeopleManagement: false,
  });

  const PRESETS = Object.freeze({
    "beijing-cn": Object.freeze({
      allowedWorkArrangements: Object.freeze(["onsite", "hybrid", "remote"]),
      onsiteCities: Object.freeze(["北京", "Beijing"]),
      remoteCountryCode: "CN",
      acceptedEmploymentTypes: Object.freeze([]),
      preferredMaxExperienceYears: null,
      stretchMaxExperienceYears: null,
      excludePeopleManagement: false,
    }),
  });

  function isPlainObject(value) {
    return (
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      (Object.getPrototypeOf(value) === Object.prototype ||
        Object.getPrototypeOf(value) === null)
    );
  }

  function rejectUnknownKeys(value, allowed, field, errors) {
    if (!isPlainObject(value)) {
      return;
    }
    const unknown = Object.keys(value).filter((key) => !allowed.has(key));
    if (unknown.length) {
      errors.push(`${field} contains unsupported fields: ${unknown.join(", ")}`);
    }
  }

  function scanSensitiveKeys(value, errors, path) {
    if (Array.isArray(value)) {
      value.forEach((item, index) =>
        scanSensitiveKeys(item, errors, `${path}[${index}]`),
      );
      return;
    }
    if (!isPlainObject(value)) {
      return;
    }
    for (const [key, child] of Object.entries(value)) {
      const normalized = key.trim().toLowerCase().replace(/-/g, "_");
      if (SENSITIVE_KEY_PARTS.some((part) => normalized.includes(part))) {
        errors.push(`${path}.${key} is a sensitive field and is not accepted`);
      }
      scanSensitiveKeys(child, errors, `${path}.${key}`);
    }
  }

  function validateContactText(value, field, errors) {
    if (value === null || value === undefined) {
      return;
    }
    if (typeof value !== "string") {
      errors.push(`${field} must be text`);
      return;
    }
    if (EMAIL_PATTERN.test(value)) {
      errors.push(`${field} must not contain an email address`);
    }
    if (PHONE_PATTERNS.some((pattern) => pattern.test(value))) {
      errors.push(`${field} must not contain a phone number`);
    }
  }

  function uniqueStrings(value, field, allowedValues) {
    if (!Array.isArray(value)) {
      throw new TypeError(`${field} must be an array`);
    }
    const result = [];
    for (const item of value) {
      if (typeof item !== "string" || !item.trim()) {
        throw new TypeError(`${field} must contain non-empty strings`);
      }
      const cleaned = item.trim();
      if (allowedValues && !allowedValues.has(cleaned)) {
        throw new TypeError(`${field} contains an unsupported value: ${cleaned}`);
      }
      if (!result.includes(cleaned)) {
        result.push(cleaned);
      }
    }
    return result;
  }

  function optionalYear(value, field) {
    if (value === undefined || value === null || value === "") {
      return null;
    }
    if (!Number.isInteger(value) || value < 0 || value > 60) {
      throw new TypeError(`${field} must be an integer from 0 to 60`);
    }
    return value;
  }

  function normalizePreferences(input) {
    if (input === undefined) {
      input = {};
    }
    if (!isPlainObject(input)) {
      throw new TypeError("preferences must be an object");
    }

    const allowedWorkArrangements = uniqueStrings(
      input.allowedWorkArrangements ??
        Array.from(DEFAULT_PREFERENCES.allowedWorkArrangements),
      "allowedWorkArrangements",
      new Set(["onsite", "hybrid", "remote"]),
    );
    const onsiteCities = uniqueStrings(
      input.onsiteCities ?? [],
      "onsiteCities",
    );
    const acceptedEmploymentTypes = uniqueStrings(
      input.acceptedEmploymentTypes ?? [],
      "acceptedEmploymentTypes",
      new Set(Array.from(EMPLOYMENT_TYPES).filter((value) => value !== "unknown")),
    );

    let remoteCountryCode = input.remoteCountryCode ?? null;
    if (remoteCountryCode === "") {
      remoteCountryCode = null;
    }
    if (remoteCountryCode !== null) {
      if (typeof remoteCountryCode !== "string") {
        throw new TypeError("remoteCountryCode must be a two-letter country code");
      }
      remoteCountryCode = remoteCountryCode.trim().toUpperCase();
      if (!/^[A-Z]{2}$/.test(remoteCountryCode)) {
        throw new TypeError("remoteCountryCode must be a two-letter country code");
      }
    }

    const preferredMaxExperienceYears = optionalYear(
      input.preferredMaxExperienceYears,
      "preferredMaxExperienceYears",
    );
    const stretchMaxExperienceYears = optionalYear(
      input.stretchMaxExperienceYears,
      "stretchMaxExperienceYears",
    );
    if (
      preferredMaxExperienceYears !== null &&
      stretchMaxExperienceYears !== null &&
      preferredMaxExperienceYears > stretchMaxExperienceYears
    ) {
      throw new TypeError(
        "preferredMaxExperienceYears cannot exceed stretchMaxExperienceYears",
      );
    }
    if (
      input.excludePeopleManagement !== undefined &&
      typeof input.excludePeopleManagement !== "boolean"
    ) {
      throw new TypeError("excludePeopleManagement must be a boolean");
    }

    return Object.freeze({
      allowedWorkArrangements: Object.freeze(allowedWorkArrangements),
      onsiteCities: Object.freeze(onsiteCities),
      remoteCountryCode,
      acceptedEmploymentTypes: Object.freeze(acceptedEmploymentTypes),
      preferredMaxExperienceYears,
      stretchMaxExperienceYears,
      excludePeopleManagement: input.excludePeopleManagement ?? false,
    });
  }

  function getPreset(name) {
    const preset = PRESETS[name];
    if (!preset) {
      throw new TypeError(`unknown preference preset: ${name}`);
    }
    return normalizePreferences({
      allowedWorkArrangements: Array.from(preset.allowedWorkArrangements),
      onsiteCities: Array.from(preset.onsiteCities),
      remoteCountryCode: preset.remoteCountryCode,
      acceptedEmploymentTypes: Array.from(preset.acceptedEmploymentTypes),
      preferredMaxExperienceYears: preset.preferredMaxExperienceYears,
      stretchMaxExperienceYears: preset.stretchMaxExperienceYears,
      excludePeopleManagement: preset.excludePeopleManagement,
    });
  }

  function validateHttpsUrl(value, platform, errors) {
    if (typeof value !== "string" || !value) {
      errors.push("source.url must be a non-empty string");
      return;
    }
    let parsed;
    try {
      parsed = new URL(value);
    } catch (_error) {
      errors.push("source.url must be a complete URL");
      return;
    }
    if (parsed.protocol !== "https:") {
      errors.push("source.url must use HTTPS");
    }
    if (parsed.username || parsed.password) {
      errors.push("source.url must not contain embedded credentials");
    }

    const expectedDomain = ASSISTED_PLATFORM_DOMAINS[platform];
    const hostname = parsed.hostname.toLowerCase().replace(/\.$/, "");
    if (
      expectedDomain &&
      hostname !== expectedDomain &&
      !hostname.endsWith(`.${expectedDomain}`)
    ) {
      errors.push(`source.url must use an official ${expectedDomain} host`);
    }
    for (const key of parsed.searchParams.keys()) {
      const normalized = key.toLowerCase().replace(/-/g, "_");
      if (SENSITIVE_QUERY_PARTS.some((part) => normalized.includes(part))) {
        errors.push("source.url must not contain authentication parameters");
        break;
      }
    }
  }

  function validateStringArray(value, field, errors, pattern) {
    if (!Array.isArray(value)) {
      errors.push(`${field} must be an array`);
      return;
    }
    for (const item of value) {
      if (typeof item !== "string" || (pattern && !pattern.test(item))) {
        errors.push(`${field} contains an invalid value`);
        return;
      }
    }
  }

  function validateNormalizedJob(job) {
    const errors = [];
    if (!isPlainObject(job)) {
      return Object.freeze({
        valid: false,
        errors: Object.freeze(["job must be an object"]),
      });
    }
    rejectUnknownKeys(job, TOP_LEVEL_KEYS, "job", errors);
    scanSensitiveKeys(job, errors, "job");
    if (job.schema_version !== 1) {
      errors.push("schema_version must be 1");
    }
    if (typeof job.id !== "string" || !job.id) {
      errors.push("id must be a non-empty string");
    }

    if (!isPlainObject(job.source)) {
      errors.push("source must be an object");
    } else {
      rejectUnknownKeys(
        job.source,
        new Set(["platform", "mode", "source_job_id", "url"]),
        "source",
        errors,
      );
      if (typeof job.source.platform !== "string" || !job.source.platform) {
        errors.push("source.platform must be a non-empty string");
      }
      validateHttpsUrl(job.source.url, job.source.platform, errors);
      if (
        Object.hasOwn(ASSISTED_PLATFORM_DOMAINS, job.source.platform) &&
        job.source.mode !== "assisted"
      ) {
        errors.push("BOSS and LinkedIn records must use assisted source mode");
      }
    }
    if (typeof job.title !== "string" || !job.title.trim()) {
      errors.push("title must be a non-empty string");
    } else {
      validateContactText(job.title, "title", errors);
    }

    if (!WORK_ARRANGEMENTS.has(job.work_arrangement)) {
      errors.push("work_arrangement is invalid");
    }

    if (!isPlainObject(job.company)) {
      errors.push("company must be an object");
    } else {
      rejectUnknownKeys(job.company, new Set(["id", "name"]), "company", errors);
      if (typeof job.company.name !== "string" || !job.company.name.trim()) {
        errors.push("company.name must be a non-empty string");
      } else {
        validateContactText(job.company.name, "company.name", errors);
      }
    }

    if (!isPlainObject(job.location) || !Array.isArray(job.location.places)) {
      errors.push("location.places must be an array");
    } else {
      rejectUnknownKeys(
        job.location,
        new Set(["raw", "places"]),
        "location",
        errors,
      );
      if (typeof job.location.raw !== "string" || !job.location.raw.trim()) {
        errors.push("location.raw must be a non-empty string");
      } else {
        validateContactText(job.location.raw, "location.raw", errors);
      }
      for (const place of job.location.places) {
        if (
          !isPlainObject(place) ||
          ![null, "string"].includes(
            place.city === null ? null : typeof place.city,
          )
        ) {
          errors.push("location.places contains an invalid city");
          break;
        }
      }
    }

    if (!isPlainObject(job.remote_eligibility)) {
      errors.push("remote_eligibility must be an object");
    } else {
      const remote = job.remote_eligibility;
      rejectUnknownKeys(
        remote,
        new Set(["scope", "allowed_countries", "allowed_regions"]),
        "remote_eligibility",
        errors,
      );
      if (!REMOTE_SCOPES.has(remote.scope)) {
        errors.push("remote_eligibility.scope is invalid");
      }
      validateStringArray(
        remote.allowed_countries,
        "remote_eligibility.allowed_countries",
        errors,
        /^[A-Z]{2}$/,
      );
      validateStringArray(
        remote.allowed_regions,
        "remote_eligibility.allowed_regions",
        errors,
      );
      if (
        remote.scope === "limited" &&
        Array.isArray(remote.allowed_countries) &&
        Array.isArray(remote.allowed_regions) &&
        remote.allowed_countries.length === 0 &&
        remote.allowed_regions.length === 0
      ) {
        errors.push("limited remote eligibility needs a country or region");
      }
      if (
        job.work_arrangement === "onsite" &&
        (remote.scope !== "not_applicable" ||
          remote.allowed_countries?.length ||
          remote.allowed_regions?.length)
      ) {
        errors.push("onsite jobs must use not_applicable remote eligibility");
      }
      if (
        job.work_arrangement === "remote" &&
        remote.scope === "not_applicable"
      ) {
        errors.push("remote jobs cannot use not_applicable remote eligibility");
      }
      if (
        ["worldwide", "unknown"].includes(remote.scope) &&
        (remote.allowed_countries?.length || remote.allowed_regions?.length)
      ) {
        errors.push(
          `${remote.scope} remote eligibility cannot include countries or regions`,
        );
      }
    }

    if (!EMPLOYMENT_TYPES.has(job.employment_type)) {
      errors.push("employment_type is invalid");
    }

    if (!isPlainObject(job.experience)) {
      errors.push("experience must be an object");
    } else {
      rejectUnknownKeys(
        job.experience,
        new Set(["min_years", "max_years", "explicit"]),
        "experience",
        errors,
      );
      const { min_years: minYears, max_years: maxYears, explicit } = job.experience;
      for (const [field, value] of [
        ["experience.min_years", minYears],
        ["experience.max_years", maxYears],
      ]) {
        if (
          value !== null &&
          (!Number.isInteger(value) || value < 0 || value > 60)
        ) {
          errors.push(`${field} must be null or an integer from 0 to 60`);
        }
      }
      if (typeof explicit !== "boolean") {
        errors.push("experience.explicit must be a boolean");
      }
      if (
        Number.isInteger(minYears) &&
        Number.isInteger(maxYears) &&
        minYears > maxYears
      ) {
        errors.push("experience minimum cannot exceed maximum");
      }
    }

    if (
      !isPlainObject(job.classification) ||
      !MANAGEMENT_VALUES.has(job.classification.people_management)
    ) {
      errors.push("classification.people_management is invalid");
    } else {
      rejectUnknownKeys(
        job.classification,
        new Set(["role_families", "seniority", "people_management"]),
        "classification",
        errors,
      );
    }
    validateContactText(job.summary, "summary", errors);

    if (!isPlainObject(job.privacy)) {
      errors.push("privacy must be an object");
    } else {
      rejectUnknownKeys(
        job.privacy,
        new Set(["visibility", "raw_description", "contains_candidate_data"]),
        "privacy",
        errors,
      );
      if (job.privacy.contains_candidate_data !== false) {
        errors.push("privacy.contains_candidate_data must be false");
      }
      if (
        isPlainObject(job.source) &&
        Object.hasOwn(ASSISTED_PLATFORM_DOMAINS, job.source.platform) &&
        job.privacy.visibility !== "local_only"
      ) {
        errors.push("BOSS and LinkedIn records must remain local_only");
      }
    }

    return Object.freeze({
      valid: errors.length === 0,
      errors: Object.freeze(errors),
    });
  }

  function requiredText(value, field, maxLength) {
    if (typeof value !== "string" || !value.trim()) {
      throw new TypeError(`${field} is required`);
    }
    const cleaned = value.trim();
    if (cleaned.length > maxLength) {
      throw new TypeError(`${field} exceeds ${maxLength} characters`);
    }
    return cleaned;
  }

  function optionalText(value, field, maxLength) {
    if (value === undefined || value === null || value === "") {
      return null;
    }
    return requiredText(value, field, maxLength);
  }

  function manualInteger(value, field) {
    if (value === undefined || value === null || value === "") {
      return null;
    }
    const number = typeof value === "number" ? value : Number(value);
    if (!Number.isInteger(number) || number < 0 || number > 60) {
      throw new TypeError(`${field} must be an integer from 0 to 60`);
    }
    return number;
  }

  function simpleId(platform, sourceJobId, url) {
    const seed = `${platform}|${sourceJobId || url}`;
    let hash = 2166136261;
    for (let index = 0; index < seed.length; index += 1) {
      hash ^= seed.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return `${platform}:${(hash >>> 0).toString(16).padStart(8, "0")}`;
  }

  function companyId(name) {
    const slug = name
      .normalize("NFKD")
      .replace(/[^\x00-\x7F]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    return slug ? slug.slice(0, 100) : null;
  }

  function createManualJob(fields, observedAt) {
    if (!isPlainObject(fields)) {
      throw new TypeError("manual job fields must be an object");
    }
    const sensitiveErrors = [];
    scanSensitiveKeys(fields, sensitiveErrors, "fields");
    if (sensitiveErrors.length) {
      throw new TypeError(sensitiveErrors.join("; "));
    }

    const platform = requiredText(fields.source, "source", 40).toLowerCase();
    if (!Object.hasOwn(ASSISTED_PLATFORM_DOMAINS, platform)) {
      throw new TypeError("source must be boss or linkedin");
    }
    const url = requiredText(fields.url, "url", 2000);
    const title = requiredText(fields.title, "title", 300);
    const companyName = requiredText(fields.company, "company", 200);
    const locationRaw = requiredText(
      fields.locationRaw,
      "locationRaw",
      500,
    );
    const arrangement = fields.workArrangement ?? "unknown";
    if (!WORK_ARRANGEMENTS.has(arrangement)) {
      throw new TypeError("workArrangement is invalid");
    }

    const city = optionalText(fields.city, "city", 120);
    const region = optionalText(fields.region, "region", 120);
    let countryCode = optionalText(fields.countryCode, "countryCode", 2);
    if (countryCode !== null) {
      countryCode = countryCode.toUpperCase();
      if (!/^[A-Z]{2}$/.test(countryCode)) {
        throw new TypeError("countryCode must be a two-letter country code");
      }
    }
    const places =
      city !== null || region !== null || countryCode !== null
        ? [{ city, region, country_code: countryCode }]
        : [];

    let remoteScope =
      arrangement === "onsite"
        ? "not_applicable"
        : fields.remoteScope ?? "unknown";
    if (!REMOTE_SCOPES.has(remoteScope)) {
      throw new TypeError("remoteScope is invalid");
    }
    const allowedCountries = uniqueStrings(
      fields.allowedCountries ?? [],
      "allowedCountries",
    ).map((code) => code.toUpperCase());
    if (allowedCountries.some((code) => !/^[A-Z]{2}$/.test(code))) {
      throw new TypeError(
        "allowedCountries must contain two-letter country codes",
      );
    }
    const allowedRegions = uniqueStrings(
      fields.allowedRegions ?? [],
      "allowedRegions",
    );
    if (remoteScope !== "limited") {
      allowedCountries.length = 0;
      allowedRegions.length = 0;
    }
    if (arrangement === "onsite") {
      remoteScope = "not_applicable";
    }

    const experienceMin = manualInteger(
      fields.experienceMinYears,
      "experienceMinYears",
    );
    const experienceMax = manualInteger(
      fields.experienceMaxYears,
      "experienceMaxYears",
    );
    if (
      experienceMin !== null &&
      experienceMax !== null &&
      experienceMin > experienceMax
    ) {
      throw new TypeError("experience minimum cannot exceed maximum");
    }
    const experienceExplicit =
      experienceMin !== null || experienceMax !== null;

    const now = observedAt === undefined ? new Date() : new Date(observedAt);
    if (Number.isNaN(now.getTime())) {
      throw new TypeError("observedAt must be a valid date");
    }
    const capturedAt = now.toISOString();
    const firstSeenOn = capturedAt.slice(0, 10);
    const sourceJobId = optionalText(
      fields.sourceJobId,
      "sourceJobId",
      200,
    );
    const summary = optionalText(fields.summary, "summary", 600);

    const job = {
      schema_version: 1,
      id: simpleId(platform, sourceJobId, url),
      source: {
        platform,
        mode: "assisted",
        source_job_id: sourceJobId,
        url,
      },
      title,
      company: { id: companyId(companyName), name: companyName },
      location: { raw: locationRaw, places },
      work_arrangement: arrangement,
      remote_eligibility: {
        scope: remoteScope,
        allowed_countries: allowedCountries,
        allowed_regions: allowedRegions,
      },
      employment_type: fields.employmentType ?? "unknown",
      compensation: {
        disclosed: false,
        currency: null,
        amount_min: null,
        amount_max: null,
        period: "unknown",
        annual_pay_periods: null,
      },
      experience: {
        min_years: experienceMin,
        max_years: experienceMax,
        explicit: experienceExplicit,
      },
      requirements: { portfolio: fields.portfolio ?? "unknown" },
      classification: {
        role_families: uniqueStrings(
          fields.roleFamilies ?? [],
          "roleFamilies",
        ),
        seniority: fields.seniority ?? "unknown",
        people_management: fields.peopleManagement ?? "unknown",
      },
      summary,
      dates: {
        published_on: fields.publishedOn ?? null,
        first_seen_on: firstSeenOn,
        captured_at: capturedAt,
      },
      provenance: {
        capture_method: "manual_entry",
        evidence: [
          {
            field: "location",
            summary: `Manual intake records the source location as ${locationRaw}.`,
            source_url: url,
            observed_at: capturedAt,
          },
          {
            field: "work_arrangement",
            summary: `Manual intake classifies the work arrangement as ${arrangement}.`,
            source_url: url,
            observed_at: capturedAt,
          },
        ],
      },
      privacy: {
        visibility: "local_only",
        raw_description: "not_stored",
        contains_candidate_data: false,
      },
    };

    const validation = validateNormalizedJob(job);
    if (!validation.valid) {
      throw new TypeError(validation.errors.join("; "));
    }
    return job;
  }

  function foldText(value) {
    return value.trim().toLocaleLowerCase("en-US");
  }

  function addReason(reasons, outcome, code, message) {
    reasons.push(Object.freeze({ outcome, code, message }));
  }

  function finalOutcome(reasons) {
    return reasons.reduce(
      (current, reason) =>
        OUTCOME_PRIORITY[reason.outcome] > OUTCOME_PRIORITY[current]
          ? reason.outcome
          : current,
      "A",
    );
  }

  function evaluateJob(job, rawPreferences) {
    const validation = validateNormalizedJob(job);
    if (!validation.valid) {
      return Object.freeze({
        id: typeof job?.id === "string" ? job.id : null,
        valid: false,
        outcome: null,
        reasons: Object.freeze([]),
        errors: validation.errors,
      });
    }

    const preferences = normalizePreferences(rawPreferences);
    const reasons = [];
    const arrangement = job.work_arrangement;

    if (arrangement === "unknown") {
      addReason(
        reasons,
        "C",
        "work_arrangement_unknown",
        "工作方式未明确，需要人工确认。",
      );
    } else if (!preferences.allowedWorkArrangements.includes(arrangement)) {
      addReason(
        reasons,
        "X",
        "work_arrangement_excluded",
        "工作方式不在当前接受范围内。",
      );
    }

    if (
      ["onsite", "hybrid"].includes(arrangement) &&
      preferences.onsiteCities.length
    ) {
      const cities = job.location.places
        .map((place) => place.city)
        .filter((city) => typeof city === "string" && city.trim())
        .map(foldText);
      const allowedCities = preferences.onsiteCities.map(foldText);
      if (!cities.length) {
        addReason(
          reasons,
          "C",
          "onsite_city_unknown",
          "线下或混合办公城市未明确，需要人工确认。",
        );
      } else if (!cities.some((city) => allowedCities.includes(city))) {
        addReason(
          reasons,
          "X",
          "onsite_city_excluded",
          "明确标注的线下或混合办公城市不在允许范围内。",
        );
      }
    }

    if (arrangement === "remote" && preferences.remoteCountryCode) {
      const remote = job.remote_eligibility;
      if (remote.scope === "unknown") {
        addReason(
          reasons,
          "C",
          "remote_eligibility_unknown",
          `远程岗位没有说明是否允许在 ${preferences.remoteCountryCode} 工作。`,
        );
      } else if (remote.scope === "limited") {
        if (remote.allowed_countries.includes(preferences.remoteCountryCode)) {
          // Explicitly allowed.
        } else if (
          remote.allowed_countries.length &&
          remote.allowed_regions.length === 0
        ) {
          addReason(
            reasons,
            "X",
            "remote_country_excluded",
            `远程岗位明确列出的工作国家不包含 ${preferences.remoteCountryCode}。`,
          );
        } else {
          addReason(
            reasons,
            "C",
            "remote_region_needs_review",
            `远程岗位的地区范围无法明确确认是否包含 ${preferences.remoteCountryCode}。`,
          );
        }
      }
    }

    const experienceFilterActive =
      preferences.preferredMaxExperienceYears !== null ||
      preferences.stretchMaxExperienceYears !== null;
    if (experienceFilterActive) {
      const experience = job.experience;
      if (!experience.explicit || experience.min_years === null) {
        addReason(
          reasons,
          "C",
          "experience_unknown",
          "职位没有明确最低经验年限，需要人工确认。",
        );
      } else if (
        preferences.stretchMaxExperienceYears !== null &&
        experience.min_years > preferences.stretchMaxExperienceYears
      ) {
        addReason(
          reasons,
          "X",
          "experience_above_stretch",
          "明确要求的最低经验年限超过当前尝试上限。",
        );
      } else if (
        preferences.preferredMaxExperienceYears !== null &&
        experience.min_years > preferences.preferredMaxExperienceYears
      ) {
        addReason(
          reasons,
          "B",
          "experience_stretch",
          "明确要求的最低经验年限高于理想范围，但仍可作为延伸机会。",
        );
      }
    }

    if (preferences.excludePeopleManagement) {
      const management = job.classification.people_management;
      if (management === "required") {
        addReason(
          reasons,
          "X",
          "people_management_required",
          "职位明确要求人员管理职责。",
        );
      } else if (management === "unknown") {
        addReason(
          reasons,
          "C",
          "people_management_unknown",
          "是否需要人员管理尚不明确。",
        );
      }
    }

    if (preferences.acceptedEmploymentTypes.length) {
      if (job.employment_type === "unknown") {
        addReason(
          reasons,
          "C",
          "employment_type_unknown",
          "雇佣类型尚不明确。",
        );
      } else if (
        !preferences.acceptedEmploymentTypes.includes(job.employment_type)
      ) {
        addReason(
          reasons,
          "X",
          "employment_type_excluded",
          "明确标注的雇佣类型不在接受范围内。",
        );
      }
    }

    if (!reasons.length) {
      addReason(
        reasons,
        "A",
        "no_explicit_conflict",
        "根据当前设置，没有发现明确冲突或待确认项。",
      );
    }

    return Object.freeze({
      id: job.id,
      valid: true,
      outcome: finalOutcome(reasons),
      reasons: Object.freeze(reasons),
      errors: Object.freeze([]),
    });
  }

  function evaluateJobs(jobs, rawPreferences) {
    if (!Array.isArray(jobs)) {
      throw new TypeError("jobs must be an array");
    }
    const preferences = normalizePreferences(rawPreferences);
    const results = jobs.map((job) => evaluateJob(job, preferences));
    const summary = { A: 0, B: 0, C: 0, X: 0, invalid: 0 };
    for (const result of results) {
      if (!result.valid) {
        summary.invalid += 1;
      } else {
        summary[result.outcome] += 1;
      }
    }
    return Object.freeze({
      preferences,
      results: Object.freeze(results),
      summary: Object.freeze(summary),
    });
  }

  function visibleResults(evaluation, options) {
    if (!isPlainObject(evaluation) || !Array.isArray(evaluation.results)) {
      throw new TypeError("evaluation must be the result of evaluateJobs");
    }
    options = options ?? {};
    if (!isPlainObject(options)) {
      throw new TypeError("options must be an object");
    }
    const showX = options.showX === true;
    return evaluation.results.filter(
      (result) => result.valid && (showX || result.outcome !== "X"),
    );
  }

  function readPublicSnapshot(snapshot, maxJobs = 1000) {
    if (!Number.isInteger(maxJobs) || maxJobs < 1 || maxJobs > 5000) {
      throw new TypeError("maxJobs must be an integer from 1 to 5000");
    }
    if (!isPlainObject(snapshot)) {
      throw new TypeError("public snapshot must be an object");
    }

    const errors = [];
    rejectUnknownKeys(
      snapshot,
      new Set(["schema_version", "updated", "jobs"]),
      "public snapshot",
      errors,
    );
    if (snapshot.schema_version !== 1) {
      errors.push("public snapshot schema_version must be 1");
    }
    const updatedDate =
      typeof snapshot.updated === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(snapshot.updated)
        ? new Date(`${snapshot.updated}T00:00:00Z`)
        : null;
    if (
      updatedDate === null ||
      Number.isNaN(updatedDate.getTime()) ||
      updatedDate.toISOString().slice(0, 10) !== snapshot.updated
    ) {
      errors.push("public snapshot updated must be an ISO date");
    }
    if (!Array.isArray(snapshot.jobs)) {
      errors.push("public snapshot jobs must be an array");
    } else if (snapshot.jobs.length > maxJobs) {
      errors.push(`public snapshot exceeds the ${maxJobs} job limit`);
    } else {
      snapshot.jobs.forEach((job, index) => {
        const validation = validateNormalizedJob(job);
        if (!validation.valid) {
          errors.push(
            `public snapshot job ${index + 1} is invalid: ${
              validation.errors[0]
            }`,
          );
          return;
        }
        if (
          !AUTOMATIC_PUBLIC_PLATFORMS.has(job.source.platform) ||
          job.source.mode !== "automatic" ||
          job.provenance.capture_method !== "public_endpoint" ||
          job.privacy.visibility !== "public_metadata" ||
          job.privacy.raw_description !== "not_stored" ||
          job.privacy.contains_candidate_data !== false
        ) {
          errors.push(
            `public snapshot job ${index + 1} is not public automatic metadata`,
          );
        }
      });
    }

    if (errors.length) {
      throw new TypeError(errors.slice(0, 3).join("; "));
    }
    return Object.freeze({
      updated: snapshot.updated,
      jobs: Object.freeze(snapshot.jobs.slice()),
    });
  }

  return Object.freeze({
    DEFAULT_PREFERENCES,
    PRESETS,
    normalizePreferences,
    getPreset,
    validateNormalizedJob,
    createManualJob,
    evaluateJob,
    evaluateJobs,
    visibleResults,
    readPublicSnapshot,
  });
});
