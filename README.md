# styd.cn 自动预约脚本（青龙面板优化版）

基于 `requests` 的 styd.cn 预约脚本，现已针对 **青龙面板** 做专门优化：拉取仓库后直接设置环境变量即可运行，无需额外脚本或命令行参数。

---

## 🚀 青龙面板三步部署

1. **拉库**：`ql repo https://github.com/<your-org>/CDU_GYM_RESERVE.git "" "" ""`
2. **新建定时任务**：命令填写 `python3 main.py`（建议放号前 1~2 分钟执行）。
3. **配置环境变量**（详见下方表格）。保存后即可手动运行验证。

> **提示**：脚本自动读取 `STYD_*` 变量；如需多账号/多任务，只需切换为 JSON 变量 `ACCOUNTS`、`TASKS`（见进阶章节）。

---

## ✅ 必填环境变量

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `STYD_COOKIE` | 账号的完整 Cookie（含 `PHPSESSID`、`UID` 等）。可直接从青龙变量管理中粘贴。 | `PHPSESSID=xxx; UID=yyy; ...` |
| `STYD_TITLE_KEYWORDS` | 课程名称关键字，支持多个值使用 `|`、`,`、`;` 或换行分隔，也可直接写成 JSON 数组。 | `健身中心（午）|健身房` |
| `STYD_TIME_KEYWORDS` | 时段关键字，写法同上。若不需要时段过滤可留空。 | `12:30 - 14:00` |

> **未设置 `STYD_TIME_KEYWORDS` 时**，脚本仅按标题筛选；如两个变量都留空，将提示配置不完整。

---

## 🔧 可选环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STYD_DATE` | 自动根据放号规则 | 指定预约日期，支持单日、多日期或范围（详见下文）。不设置时使用放号规则或当天。 |
| `STYD_STRICT_MATCH` | `true` | `true` 表示严格匹配关键字；`false` 时遇到相似课程也会尝试下单。 |
| `STYD_ALLOW_FALLBACK` | `true` | 为 `true` 时，当严格匹配失败会尝试任意可预约课程。 |
| `STYD_MAX_ATTEMPTS` | `1` | 单任务最大重试次数。 |
| `STYD_DELAY_MS` | `120,300` | 重试间隔毫秒范围，格式如 `120,300` 或 `[120,300]`。 |
| `STYD_PREFERRED_CARDS` | 空 | 会员卡优先关键字，写法同关键字变量。 |
| `STYD_SHOP_ID` | `612773420` | 部分学校需自定义场馆 `shop_id`。 |
| `STYD_DATE_RULE` | 空 | 放号规则，目前支持 `plus_7_after_17`（17:00 后抢 7 天后）。 |
| `STYD_GLOBAL_TIMEOUT_MS` | 空 | 全局超时时间（毫秒），到期后停止剩余尝试。 |
| `STYD_CONCURRENCY` | `1` | 同账号并发任务数。建议保持 `1` 以降低风控风险。 |
| `STYD_LOG_JSON` | `false` | 输出额外 JSON 日志，便于青龙日志采集。 |

所有布尔变量接受 `true/false`、`1/0`、`yes/no`、`on/off`。

> `STYD_DATE` 支持以下写法：
> - 单个日期（如 `2024-11-01`）。
> - 多个日期（使用 `,`、`|`、`;`、换行或 JSON 数组）。
> - 日期范围（如 `2024-11-01~2024-11-05`）。
>
> 输入会自动去重，并按照日期先后顺序逐一预约。

---

## 📦 进阶：多账号 / 多任务

当需要更复杂的排程时，可直接设置原生 JSON 变量：

- `ACCOUNTS`：账号数组。
- `TASKS`：任务数组。

示例：

```json
ACCOUNTS=[
  {"name":"主号","cookie":"PHPSESSID=...; UID=...;","preferred_cards":["次卡"]},
  {"name":"备号","cookie":"PHPSESSID=...; UID=...;"}
]

TASKS=[
  {
    "title_keywords":["健身中心（午）"],
    "time_keywords":["12:30 - 14:00"],
    "strict_match":true,
    "allow_fallback":false,
    "max_attempts":2,
    "delay_ms":[120,300]
  },
  {
    "title_keywords":["游泳"],
    "allow_fallback":true
  }
]
```

脚本会自动按账号遍历任务，输出成功/失败原因；任一任务失败时退出码为 `1`，青龙可据此判断任务状态。

---

## 🔍 工作流程与特性

- 自动解析「我的会员卡」页面，优先匹配 `preferred_cards` 指定的卡种。
- 支持严格匹配、回退策略与多次重试，并在日志中输出最终 URL、证据信息及 JSON 摘要。
- 内置 `plus_7_after_17` 放号规则，根据服务器时间自动切换目标日期。
- 使用移动端 UA 请求，避免网页端抓包差异；未命中课程或 Cookie 失效会清晰提示原因。

---

## 🛠️ 常见问题

| 现象 | 排查建议 |
| --- | --- |
| 日志提示 `COOKIE_INVALID` | 重新登录移动端获取最新 Cookie，并确认青龙变量无换行/空格。 |
| 未找到课程 | 提前确认放号时间，或检查关键字是否准确；必要时开启 `STYD_ALLOW_FALLBACK=false` 关闭降级。 |
| `COURSE_FULL` / `RATE_LIMIT` | 减少重试频率，适当增大 `STYD_DELAY_MS`，保持 `STYD_CONCURRENCY=1`。 |
| 想获取全部课程列表 | 手动运行 `python3 main.py show-courses --date YYYY-MM-DD --cookie "..."`。CLI 仍保留供调试使用。 |

---

## ⚠️ 免责声明

本项目仅供学习与个人效率提升，请遵守学校与平台相关规定。因违规操作产生的一切后果由使用者自行承担。

---

## 🖥️ Windows 可视化面板

在保持青龙面板用法不变的同时，新增了一个适合 Windows 用户的本地可视化面板：

1. 安装依赖（如尚未安装 `requests`、`beautifulsoup4` 等，可执行 `pip install -r requirements.txt` 或手动安装）。
2. 运行命令 `python gui.py` 即可打开界面。
3. 在界面中填写 Cookie、关键字、日期等信息，点击「执行预约」即可在日志页查看运行情况。

> 面板依旧复用脚本核心逻辑，执行效果与青龙环境保持一致。关键字、日期字段支持与环境变量相同的写法（逗号/竖线/换行或 JSON 数组、日期范围等）。

