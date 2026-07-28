# dawn-job-radar · 职途显影

给 Dawn 的私人职位雷达。每天早上 07:30（北京时间）自动从观察名单里各外企的
公开招聘接口（Greenhouse / SmartRecruiters / Workday）拉取在招职位，
合并去重后渲染成一页信息流，像刷 X 一样随时打开看。

- `companies.json` —— 观察名单。加公司、改关键词、拉黑岗位类型都在这里。
- `radar.py` —— 抓取 + 过滤 + 渲染，零第三方依赖。
- `data/jobs.json` —— 当前在架职位快照（含首见日期）。
- `docs/index.html` —— 信息流页面（GitHub Pages 指向 `main` 分支 `/docs` 目录即可）。
- `.github/workflows/radar.yml` —— 每日班车；Actions 页也能手动触发。

## 口味规则
- `title_exclude`：命中即剔除（宠物动物线已剔除数据/实验/研究类岗位）。
- `location_keywords`：留空 = 不限地点；填了 = 只留命中的。
- `ats: "pending"` 的公司是待打通名单，不参与抓取。

维护：Ciel。验收：Dawn。
