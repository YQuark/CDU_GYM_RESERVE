# styd.cn 自动预约脚本

## 项目简介
基于 `requests` 的 styd.cn 自动预约脚本，可在服务器（如青龙面板/cron）上稳定运行。

## 功能特性
- ✅ 多账号、多任务调度，单次运行自动遍历配置的所有账号与预约任务。
- ✅ 环境变量、`.env` 文件、命令行三路配置合并，优先级：命令行 > 环境变量 > `.env` > 默认值。
- ✅ 支持严格匹配 / 回退策略，未命中关键词可选择是否降级到任意可预约课程。
- ✅ 自动解析「我的会员卡」页面，提取 `member_card_id` 与 `card_cat_id`，支持关键字优先匹配。
- ✅ 强化的 `course_id` 解析：隐藏域、脚本内容、多重兜底，避免缺失导致下单失败。
- ✅ 失败归因清晰，日志同时输出人类可读信息与可选 JSON（便于青龙采集）。
- ✅ 放号规则支持：`DATE_RULE=plus_7_after_17` 可根据时间自动计算目标日期。

## 快速开始
1. **环境要求**：Python 3.9+（建议 3.10 及以上），依赖库 `requests`、`beautifulsoup4`、`lxml`。
2. **安装依赖**：
   ```bash
   pip install -U requests beautifulsoup4 lxml
   ```
3. **准备 Cookie**：
   - 使用与脚本运行环境同设备、同浏览器（移动版 styd.cn）的账号登录。
   - 打开课程列表页，从开发者工具或抓包复制完整的 Cookie 字符串。
   - Cookie 需包含 `PHPSESSID`、`UID` 等关键字段，且不可混入空格或换行。
4. **最小可运行示例**：
   - 单次直约：
     ```bash
     python main.py reserve --date 2025-10-10 --title "健身中心" --time "12:30 - 14:00" --cookie "<你的Cookie>"
     ```
   - 多账号多任务：
     ```bash
     export ACCOUNTS='[{"name":"A","cookie":"<CookieA>"}]'
     export TASKS='[{"title_keywords":["健身"],"time_keywords":["12:30"],"date":"2025-10-10"}]'
     python main.py run-tasks
     ```

## 配置说明
脚本所有配置均通过 `config.py` 解析，支持默认值、`.env` 文件、环境变量、命令行四层来源，优先级自下而上。

### 环境变量一览
| 变量 | 类型 / 示例 | 说明 |
| --- | --- | --- |
| `SHOP_ID` | 字符串，默认 `612773420` | 预约场馆的 shop_id。若学校只有一个第三方平台，此值通常不变，可用命令行 `--shop` 或环境变量覆盖。 |
| `ACCOUNTS` | JSON 数组 | 多账号配置，示例见下文。`preferred_cards` 为可选关键字列表。 |
| `TASKS` | JSON 数组 | 预约任务配置，示例见下文。 |
| `DATE_RULE` | 字符串，例如 `plus_7_after_17` | 放号规则，缺省按当天。当前实现：每天 17:00 开放第 7 天的名额。 |
| `GLOBAL_TIMEOUT_MS` | 整数 | 整体超时时间（毫秒），超过即停止后续重试。 |
| `CONCURRENCY` | 整数，默认 `1` | 同一账号内最大并发任务数，建议保持 1 以降低风控风险。 |
| `LOG_JSON` | 布尔（`true`/`false`） | 是否在日志中额外输出一行 JSON 摘要。 |

**ACCOUNTS 示例**：
```json
[
  {
    "name": "主账号",
    "cookie": "PHPSESSID=...; UID=...;",
    "preferred_cards": ["游泳", "次卡"]
  },
  {
    "name": "备用账号",
    "cookie": "PHPSESSID=...; UID=...;"
  }
]
```

**TASKS 示例**：
```json
[
  {
    "title_keywords": ["健身中心（午）"],
    "time_keywords": ["12:30 - 14:00"],
    "date": "2025-10-10",
    "strict_match": true,
    "allow_fallback": true,
    "max_attempts": 2,
    "delay_ms": [120, 300]
  }
]
```

### `.env` 示例
在项目根目录创建 `.env`：
```dotenv
SHOP_ID=612773420
ACCOUNTS=[{"name":"主账号","cookie":"PHPSESSID=..."}]
TASKS=[{"title_keywords":["健身"],"time_keywords":["12:30"],"allow_fallback":true}]
LOG_JSON=true
```

### 命令行参数
所有命令均通过 `python main.py <subcommand>` 运行：
- 通用兼容参数：`--date`、`--shop`、`--title`、`--time`、`--show`。
- `run-tasks` 专属：`--max-attempts`、`--delay-ms A B`、`--strict-match/--no-strict-match`、`--allow-fallback/--disallow-fallback`、`--concurrency`、`--global-timeout-ms`、`--log-json/--no-log-json`。
- `reserve` 专属：`--cookie`（可缺省，若 ACCOUNTS 已提供）、`--strict-match`、`--allow-fallback`。
- `show-courses`：`--date`、`--shop`、`--cookie`。

优先级：命令行 > 环境变量 > `.env` > 默认值。命令行仅覆盖显式传入的字段，其余仍使用配置来源。

## 运行方式
### 本地运行
```bash
# 查看课程
python main.py show-courses --date 2025-10-10 --cookie "<Cookie>"

# 单账号直约
python main.py reserve --date 2025-10-10 --title "健身中心" --time "12:30 - 14:00" --cookie "<Cookie>"

# 多账号任务（从环境变量读取 ACCOUNTS/TASKS）
python main.py run-tasks
```

### 青龙 / cron 调度
- **cron 表达式示例**：`55 16 * * *` 表示每天 16:55 执行一次。
- **命令示例**：
  ```bash
  cd /path/to/CDU_GYM_RESERVE && /usr/bin/python3 main.py run-tasks
  ```
- 青龙面板可直接设置环境变量（如 `ACCOUNTS`、`TASKS`）后执行同样命令。

### 并发与重试
- 同账号任务默认串行（`CONCURRENCY=1`）。如确需并行，可设置 `CONCURRENCY>1`，但建议谨慎以免触发限流。
- 每个任务根据 `max_attempts` 和 `delay_ms=[min,max]` 做随机退避，遇到 “系统繁忙/频繁操作” 时自动短间隔重试。
- 可设置 `GLOBAL_TIMEOUT_MS` 限定总运行时间，超时后不再发起新尝试。

## 任务规则与日期计算
- `DATE_RULE=plus_7_after_17`：
  - 当地时间 < 17:00 时，未显式指定日期的任务会预约 `今天+6天`；
  - 当地时间 ≥ 17:00 时，预约 `今天+7天`。
  - 代码内备注“站点放号为当地 17:00，可能需校准”，以服务器时区为准。
- 多任务示例（含日期规则与回退）：
  ```json
  {
    "DATE_RULE": "plus_7_after_17",
    "TASKS": [
      {
        "title_keywords": ["健身中心（午）"],
        "time_keywords": ["12:30 - 14:00"],
        "strict_match": true,
        "allow_fallback": false,
        "max_attempts": 3,
        "delay_ms": [80, 200]
      },
      {
        "title_keywords": ["游泳"],
        "time_keywords": ["18:00 - 19:00"],
        "allow_fallback": true
      }
    ]
  }
  ```

## 失败归因与排错
运行日志会打印：状态、原因、HTTP 状码、`code`/`msg`、最终 URL、证据等信息；如启用 `LOG_JSON=true`，额外输出一行结构化 JSON，字段包括 `ts`、`account`、`task`、`status`、`reason`、`http`、`code`、`msg`、`req_id`、`final_url`。

### reason 枚举
- `OK`：预约成功。
- `COOKIE_INVALID`：Cookie 失效，访问订单页跳转至登录或页面出现登录提示。
- `NO_MATCH`：严格匹配下未找到符合关键词的可预约课程。
- `COURSE_FULL`：找到课程但状态为满员/停止。
- `CARD_MISSING`：缺少 `member_card_id` / `card_cat_id` 或接口提示请选择会员卡。
- `COURSE_ID_MISSING`：未能解析到 `course_id`。
- `RATE_LIMIT`：接口返回系统繁忙/操作频繁等限流提示。
- `REDIRECT_LOGIN`：订单确认被重定向到登录页。
- `UNKNOWN`：其它无法归类的失败。

### 常见问题排查
- **Cookie 失效**：重新登录获取 Cookie，确认账号与脚本运行环境一致。
- **课程满员**：提前确认放号时间，可利用 `allow_fallback=true` 自动降级。
- **缺少会员卡**：确保账号在「我的会员卡」页面有可用卡片，或提供 `preferred_cards` 定位正确卡种。
- **缺少 course_id**：如页面结构变化，检查日志中的证据，必要时调整 `DEFAULT_*` 常量或更新解析逻辑。
- **系统繁忙/限频**：减少并发、拉长 `delay_ms` 区间，保持 `CONCURRENCY=1`。
- **被重定向登录**：确认 Cookie 是否完整，是否在同一终端频繁切换账号。

日志中会打印 `evidence` 与 `final_url`。需要进一步排查时，可抓取 `LOG_JSON` 行进行分析，或在调试环境中添加自定义打印查看 `RunOutcome.raw_response` 片段。

退出码：所有任务成功返回 `0`，只要有一个任务失败即返回 `1`，可直接用于脚本/青龙判断。

## 安全与速率
- 不建议设置高并发，学校平台存在限流与风控，频繁请求可能导致账号被封或 IP 限制。
- Cookie 有有效期，定期更新；遇到 `COOKIE_INVALID` 或 `REDIRECT_LOGIN` 时需立即更换。
- 建议在非放号时段测试，确认配置正确后再上线定时任务。

## 免责声明
本项目仅供学习与个人效率提升使用。请遵守学校及 styd.cn 平台相关规定，合理安排预约行为，因违规操作造成的后果自负。

## 版本变更记录
- 2025-xx-xx：重构为多账号多任务、支持配置中心与失败归因日志。
