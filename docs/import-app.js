(function () {
  "use strict";

  const core = window.JobRadarLocalFilter;
  if (!core) {
    return;
  }

  const MAX_FILE_BYTES = 5_000_000;
  const MAX_JOBS = 500;
  const jobsById = new Map();

  const elements = {
    form: document.getElementById("job-form"),
    formError: document.getElementById("form-error"),
    file: document.getElementById("job-file"),
    fileNote: document.getElementById("file-note"),
    workArrangement: document.getElementById("work-arrangement"),
    remoteFields: document.getElementById("remote-fields"),
    remoteScope: document.getElementById("remote-scope"),
    allowedCountriesField: document.getElementById("allowed-countries-field"),
    allowedRegionsField: document.getElementById("allowed-regions-field"),
    preset: document.getElementById("beijing-preset"),
    cities: document.getElementById("pref-cities"),
    country: document.getElementById("pref-country"),
    preferredExperience: document.getElementById("pref-experience"),
    stretchExperience: document.getElementById("stretch-experience"),
    excludeManagement: document.getElementById("exclude-management"),
    showX: document.getElementById("show-x"),
    resetPreferences: document.getElementById("reset-preferences"),
    preferenceError: document.getElementById("preference-error"),
    sessionNote: document.getElementById("session-note"),
    status: document.getElementById("status-message"),
    list: document.getElementById("result-list"),
    empty: document.getElementById("empty-state"),
    download: document.getElementById("download-jobs"),
    clear: document.getElementById("clear-jobs"),
    counts: {
      A: document.getElementById("count-a"),
      B: document.getElementById("count-b"),
      C: document.getElementById("count-c"),
      X: document.getElementById("count-x"),
      invalid: document.getElementById("count-invalid"),
    },
  };

  function splitList(value) {
    return value
      .split(/[,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function optionalNumber(value) {
    return value === "" ? null : Number(value);
  }

  function setMessage(element, message, isError) {
    element.textContent = message;
    element.classList.toggle("error", isError === true);
    element.hidden = !message;
  }

  function updateRemoteFields() {
    const arrangement = elements.workArrangement.value;
    const showRemote = arrangement === "remote" || arrangement === "hybrid";
    elements.remoteFields.hidden = !showRemote;
    const showLimited = showRemote && elements.remoteScope.value === "limited";
    elements.allowedCountriesField.hidden = !showLimited;
    elements.allowedRegionsField.hidden = !showLimited;
  }

  function formFields() {
    const data = new FormData(elements.form);
    return {
      source: data.get("source"),
      url: data.get("url"),
      title: data.get("title"),
      company: data.get("company"),
      locationRaw: data.get("locationRaw"),
      city: data.get("city"),
      countryCode: data.get("countryCode"),
      workArrangement: data.get("workArrangement"),
      remoteScope: data.get("remoteScope"),
      allowedCountries: splitList(String(data.get("allowedCountries") || "")),
      allowedRegions: splitList(String(data.get("allowedRegions") || "")),
      employmentType: data.get("employmentType"),
      experienceMinYears: data.get("experienceMinYears"),
      experienceMaxYears: data.get("experienceMaxYears"),
      peopleManagement: data.get("peopleManagement"),
      summary: data.get("summary"),
    };
  }

  function currentPreferences() {
    const allowedWorkArrangements = Array.from(
      document.querySelectorAll("input[data-allowed-work]:checked"),
      (input) => input.value,
    );
    const acceptedEmploymentTypes = Array.from(
      document.querySelectorAll("input[data-accepted-employment]:checked"),
      (input) => input.value,
    );
    return core.normalizePreferences({
      allowedWorkArrangements,
      onsiteCities: splitList(elements.cities.value),
      remoteCountryCode: elements.country.value,
      acceptedEmploymentTypes,
      preferredMaxExperienceYears: optionalNumber(
        elements.preferredExperience.value,
      ),
      stretchMaxExperienceYears: optionalNumber(
        elements.stretchExperience.value,
      ),
      excludePeopleManagement: elements.excludeManagement.checked,
    });
  }

  function addJobs(jobs) {
    let added = 0;
    let duplicates = 0;
    let conflicts = 0;
    let invalid = 0;
    const invalidMessages = [];

    for (const job of jobs) {
      const validation = core.validateNormalizedJob(job);
      if (!validation.valid) {
        invalid += 1;
        if (invalidMessages.length < 3) {
          invalidMessages.push(validation.errors[0]);
        }
        continue;
      }
      const existing = jobsById.get(job.id);
      if (existing) {
        if (JSON.stringify(existing) === JSON.stringify(job)) {
          duplicates += 1;
        } else {
          conflicts += 1;
        }
        continue;
      }
      jobsById.set(job.id, job);
      added += 1;
    }

    render();
    const parts = [`已加入 ${added} 个职位`];
    if (duplicates) parts.push(`忽略 ${duplicates} 个重复项`);
    if (conflicts) parts.push(`拒绝 ${conflicts} 个 ID 冲突项`);
    if (invalid) parts.push(`拒绝 ${invalid} 个无效项`);
    const detail = invalidMessages.length
      ? `：${invalidMessages.join("；")}`
      : "";
    setMessage(elements.status, `${parts.join("，")}${detail}。`, invalid > 0);
  }

  function resultCard(job, result) {
    const article = document.createElement("article");
    article.className = "result-card";
    article.dataset.outcome = result.outcome;

    const head = document.createElement("div");
    head.className = "result-card-head";
    const titleWrap = document.createElement("div");
    const company = document.createElement("p");
    company.className = "result-company";
    company.textContent = job.company.name;
    const title = document.createElement("h3");
    title.className = "result-title";
    title.textContent = job.title;
    titleWrap.append(company, title);

    const badge = document.createElement("span");
    badge.className = "outcome-badge";
    badge.textContent = result.outcome;
    badge.setAttribute("aria-label", `${result.outcome} 类职位`);
    head.append(titleWrap, badge);

    const meta = document.createElement("p");
    meta.className = "result-meta";
    meta.textContent = `${job.location.raw} · ${job.work_arrangement} · ${job.source.platform}`;

    const reasons = document.createElement("ul");
    reasons.className = "result-reasons";
    for (const reason of result.reasons) {
      const item = document.createElement("li");
      item.textContent = reason.message;
      reasons.appendChild(item);
    }

    const link = document.createElement("a");
    link.className = "source-link";
    link.href = job.source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.referrerPolicy = "no-referrer";
    link.textContent = "打开官方职位页面 ↗";

    article.append(head, meta, reasons, link);
    return article;
  }

  function render() {
    let preferences;
    try {
      preferences = currentPreferences();
      setMessage(elements.preferenceError, "");
    } catch (error) {
      setMessage(elements.preferenceError, error.message, true);
      return;
    }

    const jobs = Array.from(jobsById.values());
    const evaluation = core.evaluateJobs(jobs, preferences);
    for (const outcome of ["A", "B", "C", "X", "invalid"]) {
      elements.counts[outcome].textContent = evaluation.summary[outcome];
    }

    elements.list.replaceChildren();
    const visible = core.visibleResults(evaluation, {
      showX: elements.showX.checked,
    });
    const resultById = new Map(
      visible.map((result) => [result.id, result]),
    );
    for (const job of jobs) {
      const result = resultById.get(job.id);
      if (result) {
        elements.list.appendChild(resultCard(job, result));
      }
    }

    const count = jobs.length;
    elements.sessionNote.textContent = count
      ? `当前标签页有 ${count} 个职位；刷新或关闭后即消失。`
      : "当前标签页还没有职位。";
    elements.empty.hidden = count > 0;
    elements.download.disabled = count === 0;
    elements.clear.disabled = count === 0;
  }

  function applyPreset() {
    const preset = core.getPreset("beijing-cn");
    for (const input of document.querySelectorAll(
      "input[data-allowed-work]",
    )) {
      input.checked = preset.allowedWorkArrangements.includes(input.value);
    }
    elements.cities.value = preset.onsiteCities.join(", ");
    elements.country.value = preset.remoteCountryCode;
    elements.preferredExperience.value = "";
    elements.stretchExperience.value = "";
    elements.excludeManagement.checked = false;
    for (const input of document.querySelectorAll(
      "input[data-accepted-employment]",
    )) {
      input.checked = false;
    }
    setMessage(elements.status, "已套用北京线下／中国可远程条件。");
    render();
  }

  function resetPreferences() {
    for (const input of document.querySelectorAll(
      "input[data-allowed-work]",
    )) {
      input.checked = true;
    }
    elements.cities.value = "";
    elements.country.value = "";
    elements.preferredExperience.value = "";
    elements.stretchExperience.value = "";
    elements.excludeManagement.checked = false;
    elements.showX.checked = false;
    for (const input of document.querySelectorAll(
      "input[data-accepted-employment]",
    )) {
      input.checked = false;
    }
    setMessage(elements.status, "已恢复中立筛选条件。");
    render();
  }

  function payloadJobs(payload) {
    if (Array.isArray(payload)) {
      return payload;
    }
    if (
      payload &&
      typeof payload === "object" &&
      !Array.isArray(payload) &&
      Object.keys(payload).length === 1 &&
      Array.isArray(payload.jobs)
    ) {
      return payload.jobs;
    }
    throw new TypeError("JSON 必须是职位数组，或只包含 jobs 数组的对象");
  }

  async function handleFile() {
    const file = elements.file.files[0];
    if (!file) return;
    setMessage(elements.status, "");
    elements.fileNote.textContent = file.name;
    try {
      if (file.size > MAX_FILE_BYTES) {
        throw new TypeError("文件超过 5 MB 安全限制");
      }
      const payload = JSON.parse(await file.text());
      const jobs = payloadJobs(payload);
      if (jobs.length > MAX_JOBS) {
        throw new TypeError("一次最多导入 500 个职位");
      }
      addJobs(jobs);
    } catch (error) {
      setMessage(elements.status, `导入失败：${error.message}`, true);
    } finally {
      elements.file.value = "";
    }
  }

  function downloadJobs() {
    const content = `${JSON.stringify(Array.from(jobsById.values()), null, 2)}\n`;
    const blob = new Blob([content], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `job-radar-local-${new Date()
      .toISOString()
      .slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setMessage(elements.status, "已在本机生成标准 JSON 下载。");
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    setMessage(elements.formError, "");
    try {
      const job = core.createManualJob(formFields());
      addJobs([job]);
      elements.form.reset();
      elements.workArrangement.value = "onsite";
      updateRemoteFields();
    } catch (error) {
      setMessage(elements.formError, error.message, true);
    }
  });

  elements.file.addEventListener("change", handleFile);
  elements.workArrangement.addEventListener("change", updateRemoteFields);
  elements.remoteScope.addEventListener("change", updateRemoteFields);
  elements.preset.addEventListener("click", applyPreset);
  elements.resetPreferences.addEventListener("click", resetPreferences);
  elements.download.addEventListener("click", downloadJobs);
  elements.clear.addEventListener("click", () => {
    jobsById.clear();
    setMessage(elements.status, "当前标签页中的职位数据已清空。");
    render();
  });

  for (const input of document.querySelectorAll(
    '.preference-panel input[type="checkbox"], .preference-panel input[type="number"]',
  )) {
    input.addEventListener("change", render);
  }
  elements.cities.addEventListener("input", render);
  elements.country.addEventListener("input", render);

  updateRemoteFields();
  render();
})();
