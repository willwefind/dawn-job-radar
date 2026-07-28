# dawn-job-radar · 职途显影

一个可复用、可审查、重视隐私的职位雷达。项目从公司公开招聘接口
（Greenhouse、SmartRecruiters、Workday）采集职位事实，生成静态信息流，
并提供完全在浏览器本地运行的辅助筛选页面。

它不会自动投递、登录招聘账号或替用户发送任何内容。

## 两条数据路径

### 公共职位流

`radar.py` 定期读取公开 ATS 数据，保留职位名称、公司、公开地点、原始链接和
首次发现日期，再生成 `data/jobs.json`、`docs/jobs.js` 与
`docs/index.html`。

Greenhouse 与 Workday 来源还会生成 `data/jobs.normalized.json`：描述正文
只在运行时内存中用于提取经验、工作方式、Remote 地域、作品集和人员管理等明确
事实，落盘时不保存职位描述全文。无法可靠确认的字段保持 `unknown`。

Workday 会先应用现有公开采集范围，再读取保留下来的职位详情；单个详情请求失败时
会降级为标题、地点和链接，不会拖垮整家公司，也不会把缺失信息猜成确定结论。

公开职位流中的“早期”“资深”“技术”只表示标题关键词信号，不代表候选人适配
结论。页面默认不排除任何一类标题。

### 本地辅助筛选

`docs/import.html` 接受手动录入或标准化 JSON。筛选偏好和导入数据只保留在
当前浏览器标签页的内存中，刷新或关闭后即消失；页面不上传、不登录、不使用
浏览器持久化存储，也不会自动投递。

筛选使用 A/B/C/X 结果：

- A：当前条件下没有发现明确冲突；
- B：超过理想范围但仍在可尝试范围；
- C：信息不足，需要人工确认；
- X：存在明确、可追溯的硬性冲突。

只有 X 可以默认隐藏。未知信息不能作为拒绝依据。

## 主要文件

- `companies.json`：公开来源清单及当前采集范围；
- `radar.py`：ATS 采集、去重和静态信息流生成；
- `job_facts.py`：不保留描述全文的公开职位事实提取；
- `data/jobs.json`：生成的公开职位快照；
- `data/jobs.normalized.json`：逐步覆盖各 ATS 的标准化公开职位事实；
- `template.html`：公共职位流的页面源模板；
- `docs/index.html`：由 `template.html` 生成的公共职位流；
- `docs/import.html`：本地辅助筛选页面；
- `schemas/job.schema.json`：标准化职位数据格式；
- `sources.json`：来源能力与安全边界；
- `.github/workflows/radar.yml`：定时更新工作流。

`companies.json` 里的 `location_keywords` 与 `title_exclude` 目前只用于控制
旧采集管线的范围，不是候选人适配判断。后续标准化管线会把职位事实与用户偏好
彻底分开。

## 本地验证

```bash
python -m py_compile radar.py job_facts.py import_jobs.py
python -m unittest discover -s tests
node --test tests/test_local_filter_core.js
```

运行抓取和生成：

```bash
python radar.py
```

## 隐私与安全

仓库只应包含源代码、公开职位事实、通用规则和虚构示例。请勿提交真实简历、
联系方式、申请记录、招聘者对话、面试笔记、私人评价、Cookie、令牌或其他凭据。

职位链接只允许使用不含账号信息的 HTTP/HTTPS 地址。使用任何职位信息前，请回到
原始招聘页面核对地点、资格、职责和有效期。
