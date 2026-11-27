"""Exercise the checked-in public snapshot in a real headless browser."""

import json
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"


def net_revenue(rows):
    satang = sum(row["net"] for row in rows)
    return f"฿{Decimal(satang) / 100:,.2f}"


def main():
    sales = json.loads((DASHBOARD / "data/snapshot.json").read_text())["sales"]
    handler = partial(SimpleHTTPRequestHandler, directory=str(DASHBOARD))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, sync_playwright() as playwright:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.locator("#net")).to_have_text(net_revenue(sales))
            expect(page.locator("#report")).to_be_visible()

            page.get_by_role("combobox", name="Sales channel").select_option("shopee")
            expect(page.locator("#net")).to_have_text(net_revenue(r for r in sales if r["channel"] == "shopee"))
            page.get_by_label("Reporting window").select_option("first")
            expect(page.locator("#trend button")).to_have_count(7)
            expect(page.get_by_text("No settlement files cover this window.", exact=True)).to_be_visible()
            expect(page.get_by_text("No marketing activity covers this window.", exact=True)).to_be_visible()
            assert not errors, errors
            browser.close()
        finally:
            server.shutdown()
            thread.join()
    print("Dashboard smoke passed: first render, sales filter, date window and both empty states.")


if __name__ == "__main__":
    main()
