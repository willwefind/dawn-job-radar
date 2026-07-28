(function () {
  "use strict";

  const core = window.JobRadarLocalFilter;
  if (!core) {
    return;
  }

  const MAX_FILE_BYTES = 5_000_000;
  const MAX_JOBS = 500;
  const MAX_PUBLIC_JOBS = 1_000;
  const FOCUS_STORAGE_KEY = "job-radar.focus-directions.v1";
  const jobsById = new Map();
  let publicSnapshot = null;
  let focusDirections = [];
  let focusSequence = 0;

  const elements = {
    form: document.getElementById("job-form"),
    formError: document.getElementById("form-error"),
    file: document.getElementById("job-file"),
    fileNote: document.getElementById("file-note"),
    loadPublicJobs: document.getElementById("load-public-jobs"),
    publicSnapshotNote: document.getElementById("public-snapshot-note"),
    workArrangement: document.getElementById("work-arrangement"),
    remoteFields: document.getElementById("remote-fields"),
    remoteScope: document.getElementById("remote-scope"),
    allowedCountriesField: document.getElementById("allowed-countries-field"),
    allowedRegionsField: document.getElementById("allowed-regions-field"),
    preset: document.getElementById("beijing-preset"),
    focusForm: document.getElementById("focus-form"),
    focusName: document.getElementById("focus-name"),
    focusKeywords: document.getElementById("focus-keywords"),
    focusError: document.getElementById("focus-error"),
    focusList: document.getElementById("focus-list"),
    focusEmpty: document.getElementById("focus-empty"),
    rememberFocus: document.getElementById("remember-focus"),
    focusStorageNote: document.getElementById("focus-storage-note"),
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
    emptyTitle: document.getElementById("empty-title"),
    emptyCopy: document.getElementById("empty-copy"),
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

  function nextFocusId() {
    focusSequence += 1;
    return `focus-${Date.now().toString(36)}-${focusSequence.toString(36)}`;
  }

  function focusPayload() {
    return focusDirections.map((direction) => ({
      id: direction.id,
      name: direction.name,
      keywords: Array.from(direction.keywords),
      active: direction.active,
    }));
  }

  function saveFocusDirections() {
    if (!elements.rememberFocus.checked) return;
    try {
      localStorage.setItem(FOCUS_STORAGE_KEY, JSON.stringify(focusPayload()));
      elements.focusStorageNote.textContent =
        "只保存了关注方向的名称、匹配词和启用状态。";
    } catch {
      elements.rememberFocus.checked = false;
      elements.rememberFocus.disabled = true;
      elements.focusStorageNote.textContent =
        "当前浏览器不允许本地保存；关注方向仍可在本次使用中生效。";
    }
  }

  function removeStoredFocusDirections() {
    try {
      localStorage.removeItem(FOCUS_STORAGE_KEY);
      elements.focusStorageNote.textContent =
        "不会保存职位、JD、筛选结果或私人备注。";
    } catch {
      elements.focusStorageNote.textContent =
        "无法访问本地存储；当前关注方向仍只在本次使用中生效。";
    }
  }

  function loadStoredFocusDirections() {
    try {
      const stored = localStorage.getItem(FOCUS_STORAGE_KEY);
      if (!stored) return;
      focusDirections = Array.from(
        core.normalizeFocusDirections(JSON.parse(stored)),
      );
      elements.rememberFocus.checked = true;
      elements.focusStorageNote.textContent =
        "已载入保存在这台设备上的关注方向。";
    } catch {
      focusDirections = [];
      removeStoredFocusDirections();
      elements.focusStorageNote.textContent =
        "已忽略无法识别的本地关注方向数据。";
    }
  }

  function replaceFocusDirection(id, fields) {
    const index = focusDirections.findIndex((direction) => direction.id === id);
    if (index < 0) return;
    const current = focusDirections[index];
    const updated = core.normalizeFocusDirection({
      id: current.id,
      name: fields.name ?? current.name,
      keywords: fields.keywords ?? Array.from(current.keywords),
      active: fields.active ?? current.active,
    });
    focusDirections = [
      ...focusDirections.slice(0, index),
      updated,
      ...focusDirections.slice(index + 1),
    ];
    saveFocusDirections();
    renderFocusDirections();
    render();
  }

  function renderFocusDirections() {
    elements.focusList.replaceChildren();
    elements.focusEmpty.hidden = focusDirections.length > 0;

    for (const direction of focusDirections) {
      const row = document.createElement("div");
      row.className = "focus-row";

      const main = document.createElement("div");
      main.className = "focus-row-main";

      const active = document.createElement("input");
      active.className = "focus-active";
      active.type = "checkbox";
      active.checked = direction.active;
      active.setAttribute("aria-label", `启用关注方向：${direction.name}`);
      active.addEventListener("change", () => {
        replaceFocusDirection(direction.id, { active: active.checked });
      });

      const name = document.createElement("input");
      name.className = "focus-row-name";
      name.type = "text";
      name.maxLength = 60;
      name.value = direction.name;
      name.setAttribute("aria-label", "关注方向名称");

      const remove = document.createElement("button");
      remove.className = "focus-delete";
      remove.type = "button";
      remove.textContent = "删除";
      remove.setAttribute("aria-label", `删除关注方向：${direction.name}`);
      remove.addEventListener("click", () => {
        focusDirections = focusDirections.filter(
          (item) => item.id !== direction.id,
        );
        saveFocusDirections();
        setMessage(elements.focusError, "");
        renderFocusDirections();
        render();
      });

      const keywords = document.createElement("input");
      keywords.className = "focus-row-keywords";
      keywords.type = "text";
      keywords.maxLength = 500;
      keywords.value = direction.keywords.join(", ");
      keywords.setAttribute("aria-label", `${direction.name}的匹配词`);

      const applyEdits = () => {
        try {
          replaceFocusDirection(direction.id, {
            name: name.value,
            keywords: splitList(keywords.value),
          });
          setMessage(elements.focusError, "");
        } catch (error) {
          setMessage(elements.focusError, error.message, true);
          renderFocusDirections();
        }
      };
      name.addEventListener("change", applyEdits);
      keywords.addEventListener("change", applyEdits);

      main.append(active, name, remove);
      row.append(main, keywords);
      elements.focusList.appendChild(row);
    }
  }

  function addFocusDirection(event) {
    event.preventDefault();
    setMessage(elements.focusError, "");
    try {
      const direction = core.normalizeFocusDirection({
        id: nextFocusId(),
        name: elements.focusName.value,
        keywords: splitList(elements.focusKeywords.value),
        active: true,
      });
      focusDirections = Array.from(
        core.normalizeFocusDirections([...focusDirections, direction]),
      );
      elements.focusForm.reset();
      saveFocusDirections();
      renderFocusDirections();
      render();
    } catch (error) {
      setMessage(elements.focusError, error.message, true);
    }
  }

  function toggleFocusStorage() {
    if (elements.rememberFocus.checked) {
      saveFocusDirections();
      setMessage(elements.status, "关注方向已保存在这台设备上。");
    } else {
      removeStoredFocusDirections();
      setMessage(elements.status, "已停止本地保存；当前方向仍保留到页面关闭。");
    }
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

  function addJobs(jobs, sourceLabel) {
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
    const parts = [
      `${sourceLabel ? `${sourceLabel}：` : ""}已加入 ${added} 个职位`,
    ];
    if (duplicates) parts.push(`忽略 ${duplicates} 个重复项`);
    if (conflicts) parts.push(`拒绝 ${conflicts} 个 ID 冲突项`);
    if (invalid) parts.push(`拒绝 ${invalid} 个无效项`);
    const detail = invalidMessages.length
      ? `：${invalidMessages.join("；")}`
      : "";
    setMessage(elements.status, `${parts.join("，")}${detail}。`, invalid > 0);
  }

  function configurePublicSnapshot() {
    const rawSnapshot = window.JOB_RADAR_PUBLIC_SNAPSHOT;
    if (rawSnapshot === undefined) {
      elements.publicSnapshotNote.textContent =
        "每日公开快照尚未生成；仍可导入本地 JSON 或手动添加。";
      return;
    }
    try {
      publicSnapshot = core.readPublicSnapshot(
        rawSnapshot,
        MAX_PUBLIC_JOBS,
      );
      const count = publicSnapshot.jobs.length;
      elements.publicSnapshotNote.textContent = count
        ? `更新于 ${publicSnapshot.updated}，共 ${count} 个公开职位；载入后仅停留在当前标签页。`
        : `更新于 ${publicSnapshot.updated}，当前暂无公开职位。`;
      elements.loadPublicJobs.disabled = count === 0;
    } catch {
      publicSnapshot = null;
      elements.publicSnapshotNote.textContent =
        "公开快照未通过安全校验；仍可导入本地 JSON 或手动添加。";
      elements.loadPublicJobs.disabled = true;
    }
  }

  function loadPublicJobs() {
    if (!publicSnapshot) {
      setMessage(elements.status, "当前没有可安全载入的公开快照。", true);
      return;
    }
    addJobs(publicSnapshot.jobs, "公开快照");
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

    const matches = core.matchingFocusDirections(job, focusDirections);
    const focusMatches = document.createElement("div");
    focusMatches.className = "focus-match-list";
    for (const direction of matches) {
      const tag = document.createElement("span");
      tag.className = "focus-match";
      tag.textContent = direction.name;
      focusMatches.appendChild(tag);
    }

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

    article.append(head, meta);
    if (matches.length) article.appendChild(focusMatches);
    article.append(reasons, link);
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
    const focusedJobs = core.filterJobsByFocus(jobs, focusDirections);
    const evaluation = core.evaluateJobs(focusedJobs, preferences);
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
    const activeFocusCount = focusDirections.filter(
      (direction) => direction.active,
    ).length;
    elements.sessionNote.textContent = count
      ? activeFocusCount
        ? `当前标签页有 ${count} 个职位；关注方向匹配 ${focusedJobs.length} 个。`
        : `当前标签页有 ${count} 个职位；刷新或关闭后即消失。`
      : "当前标签页还没有职位。";
    elements.empty.hidden = visible.length > 0;
    if (count === 0) {
      elements.emptyTitle.textContent = "职位会在这里显影。";
      elements.emptyCopy.textContent =
        "先载入每日公开职位、选择本地 JSON，或手动添加一个职位。";
    } else {
      elements.emptyTitle.textContent = "当前视图没有可显示的职位。";
      elements.emptyCopy.textContent = activeFocusCount
        ? "可以停用或修改关注方向，也可以调整筛选条件。"
        : "可以调整筛选条件，或选择显示存在明确冲突的 X 类岗位。";
    }
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
  elements.focusForm.addEventListener("submit", addFocusDirection);
  elements.rememberFocus.addEventListener("change", toggleFocusStorage);
  elements.loadPublicJobs.addEventListener("click", loadPublicJobs);
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

  loadStoredFocusDirections();
  renderFocusDirections();
  configurePublicSnapshot();
  updateRemoteFields();
  render();
})();
