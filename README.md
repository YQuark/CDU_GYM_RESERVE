# CDU Gym Reserve Scripts

This repository contains two complementary automation scripts that help submit course reservations on [styd.cn](https://www.styd.cn/) for the CDU gym space `e74abd6e`.

- **`main.py`** – A hybrid workflow that fetches the course list with `requests`, applies filtering heuristics, and then triggers a Playwright-based checkout flow for the chosen class.
- **`main_playwright.py`** – A pure Playwright asynchronous workflow that handles the complete flow (fetching, filtering, and booking) within a single script.

Both scripts require a valid session cookie string copied from the mobile site; paste it into the `RAW_COOKIE` constant near the top of each file before running the tools.

## Requirements

- Python 3.9+
- [Playwright](https://playwright.dev/python/) with the WebKit browser drivers installed
- `requests`, `beautifulsoup4`, and `lxml`

Install the Python dependencies and Playwright browsers with:

```bash
pip install -r requirements.txt  # or install requests, playwright, beautifulsoup4, lxml manually
playwright install webkit
```

> **Note:** The project does not ship with a `requirements.txt`; feel free to create one that pins the packages listed above.

## Configuration

Both scripts expose configuration constants at the top of the file:

- Target base URL, space ID, and search/order endpoints
- Mobile user-agent string
- `RAW_COOKIE` with your captured cookie header
- Keyword/time filters, retry policies, and occupancy limits that drive course selection heuristics

Adjust these values to match your own shop/space and booking preferences.

## Usage

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

## Notes & Tips

- Ensure your cookie string remains valid; login expiration is the most common failure point.
- Adjust the keyword/time windows to prioritize your preferred classes.
- Consider scheduling the script via cron or another task runner for timely execution.
- If the styd.cn frontend changes, inspect the DOM to update selectors or tweak the heuristics accordingly.

Happy reserving!
