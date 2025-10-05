# CDU Gym Reserve Scripts

This repository contains automation scripts that help submit course reservations on [styd.cn](https://www.styd.cn/) for the CDU gym space `e74abd6e`.

- **`main.py`** – A hybrid workflow that fetches the course list with `requests`, applies filtering heuristics, and then triggers a Playwright-based checkout flow for the chosen class.
- **`main_playwright.py`** – A pure Playwright asynchronous workflow that handles the complete flow (fetching, filtering, and booking) within a single script.
- **`main_request.py`** – A pure `requests` implementation that performs the entire reservation flow via HTTP calls. It now includes resilient fallbacks for `course_id`, payload diagnostics, retry-on-busy logic for `order_confirm`, and JSON-aware success detection to handle the newer API responses gracefully.

Both scripts require a valid session cookie string copied from the mobile site; paste it into the `RAW_COOKIE` constant near the top of each file before running the tools.

## Requirements / 运行环境

- Python 3.9+
- [Playwright](https://playwright.dev/python/) with the WebKit browser drivers installed
- `requests`, `beautifulsoup4`, and `lxml`

Install the Python dependencies and Playwright browsers with:

```bash
pip install -r requirements.txt  # or install requests, playwright, beautifulsoup4, lxml manually
playwright install webkit
```

> **Note:** The project does not ship with a `requirements.txt`; feel free to create one that pins the packages listed above.

## Configuration / 参数配置

Both scripts expose configuration constants at the top of the file:

- Target base URL, space ID, and search/order endpoints
- Mobile user-agent string
- `RAW_COOKIE` with your captured cookie header
- Keyword/time filters, retry policies, and occupancy limits that drive course selection heuristics

Adjust these values to match your own shop/space and booking preferences.

> 默认 `SHOP_ID` 为 `612773420`。若学校只有一个第三方平台，此值通常不变；如需调整可通过命令行 `--shop` 或环境变量 `SHOP_ID` 覆盖。

## Usage / 使用方法

### `main.py`

This synchronous helper first queries the available courses for a given date and shop, picks the best match, and then attempts the booking flow. Run it with:

```bash
python main.py --date 2025-10-09 --shop 612773420 --type 1 --tries 2
```

Key options:

- `--date` – Target date in `YYYY-MM-DD` format
- `--shop` – Shop ID as used by styd.cn
- `--type` – Search category (defaults to mobile type `1`)
- `--course-id` – Skip auto-selection and directly attempt a known course ID
- `--show` – Launch the Playwright browser in headed mode for debugging
- `--tries` – Number of retries for booking failures

### `main_playwright.py`

The asynchronous variant can be invoked directly and mirrors the command-line options of `main.py`. It navigates to the order page, waits for the booking button to become clickable, and handles the native JavaScript confirmation dialog before observing the `order_confirm` POST response.

Run it with:

```bash
python main_playwright.py --date 2025-10-09 --shop 612773420 --type 1 --tries 2
```

Add `--show` to visualize the headful browser session.

### `main_request.py`

This command-line helper sends the entire reservation flow via HTTP requests, making it easy to schedule in cron or other headless environments. It will:

- Retrieve classes, parse hidden form fields, and auto-select membership cards.
- Backfill missing `course_id` values using layered fallbacks.
- Print the key payload identifiers before submitting to help troubleshoot missing data.
- Retry the `order_confirm` POST once when the server reports it is busy.
- Parse the JSON response to confirm success even when the server returns Unicode-escaped messages.

Run it with:

```bash
python main_request.py --date 2025-10-09 --shop 612773420
```

### 中文指南

`main_request.py` 现已强化为纯 `requests` 流程，更适合在无界面环境中执行。其主要特性包括：

- 自动拉取课程、解析隐藏字段并匹配会员卡；
- 针对 `course_id` 提供多层兜底，必要时使用自定义默认值；
- 在提交前打印关键字段，缺失时直接终止，方便排查；
- 当接口返回“系统繁忙”时短暂等待后再次尝试提交；
- 针对 JSON/Unicode 响应判断“预约成功”，避免误报失败。

执行示例：

```bash
python main_request.py --date 2025-10-09 --shop 612773420
```

## Notes & Tips / 使用提示

- Ensure your cookie string remains valid; login expiration is the most common failure point.
- Adjust the keyword/time windows to prioritize your preferred classes.
- Consider scheduling the script via cron or another task runner for timely execution.
- If the styd.cn frontend changes, inspect the DOM to update selectors or tweak the heuristics accordingly.

Happy reserving!
