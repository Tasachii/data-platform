"""Exercise the checked-in public snapshot in a real headless browser."""

import json
import re
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"


def money(satang):
    amount = Decimal(satang) / 100
    return f"{'-' if amount < 0 else ''}฿{abs(amount):,.2f}"


def check_sales_total(page, rows):
    net = sum(row["net"] for row in rows)
    expect(page.locator("#net")).to_have_text(f"{Decimal(net) / 100_000_000:.2f}")
    expect(page.locator("#net-unit")).to_have_text("million baht")
    expect(page.locator(".net-total strong")).to_have_text(money(net))
    expect(page.locator(".net-total strong")).to_be_visible()


def check_number_type(page):
    page.evaluate("async () => { await document.fonts.ready; }")
    expect(page.locator("#net")).to_have_css("font-family", re.compile("IBM Plex Mono"))
    assert page.evaluate("document.fonts.check('500 42px \\\"IBM Plex Mono\\\"')")
    digit_widths = page.locator("#net").evaluate(
        """target => {
          const sample = document.createElement("span");
          const style = getComputedStyle(target);
          sample.style.cssText = `position:fixed;left:-10000px;white-space:nowrap;
            font:${style.font};font-family:${style.fontFamily};font-variant-numeric:${style.fontVariantNumeric};
            font-feature-settings:${style.fontFeatureSettings};letter-spacing:${style.letterSpacing}`;
          document.body.append(sample);
          const widths = [..."0123456789"].map(digit => {
            sample.textContent = digit.repeat(6);
            return sample.getBoundingClientRect().width;
          });
          sample.remove();
          return widths;
        }"""
    )
    assert max(digit_widths) - min(digit_widths) < 0.1, digit_widths
    gap_right_edges = page.locator(".gap-line strong").evaluate_all(
        "nodes => nodes.map(node => node.getBoundingClientRect().right)"
    )
    assert max(gap_right_edges) - min(gap_right_edges) < 0.1, gap_right_edges


def check_report(page, data):
    sales = data["sales"]
    check_sales_total(page, sales)
    check_number_type(page)
    first = [r for r in sales if r["date"] == sales[0]["date"]]
    daily_net = money(sum(r["net"] for r in first))
    bars = page.locator("#trend button")
    bars.first.focus()
    expect(page.locator("#inspect")).to_contain_text(daily_net)
    bars.first.press("End")
    expect(bars.last).to_be_focused()
    page.get_by_text("Daily figures", exact=True).click()
    expect(page.locator("#sales-table tbody tr").first).to_contain_text(daily_net)
    page.get_by_text("Daily figures", exact=True).click()

    gaps = [money(r["gap"]) for r in data["reconciliation"]]
    expect(page.locator(".gap-line strong")).to_have_text(gaps)
    page.get_by_label("Alert severity").select_option("WARNING")
    warnings = sum(r["alerts"] for r in data["alerts"] if r["severity"] == "WARNING")
    expect(page.locator("#alerts .metric")).to_have_text(str(warnings))
    page.get_by_text("Alert dates and rules", exact=True).click()
    expect(page.locator("#alert-table tbody tr")).to_have_count(warnings)

    facebook = [r for r in data["marketing"] if r["platform"] == "facebook"]
    source = page.locator("#marketing tbody tr").filter(has_text="Facebook")
    expect(source).to_contain_text(money(sum(r["revenue"] for r in facebook)))
    expect(source).to_contain_text(money(sum(r["spend"] for r in facebook)))
    expect(page.locator("#coverage dt")).to_have_text(
        ["Orders · 30 source days", "Payments · 7 source days", "Ad spend · 14 source days"]
    )
    if page.viewport_size["width"] < 560:
        expect(source.locator(".mobile-label").first).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert source.evaluate("row => row.getBoundingClientRect().right <= innerWidth")
    channel = page.get_by_role("combobox", name="Sales channel")
    channel.select_option("shopee")
    check_sales_total(page, (r for r in sales if r["channel"] == "shopee"))
    window = page.get_by_label("Reporting window")
    for value, days in [("7", 7), ("14", 14), ("first", 7)]:
        window.select_option(value)
        expect(bars).to_have_count(days)
    expect(page.get_by_text("No settlement files cover this window.", exact=True)).to_be_visible()
    expect(page.get_by_text("No marketing activity covers this window.", exact=True)).to_be_visible()
    window.select_option("all")
    channel.select_option("all")
    check_sales_total(page, sales)


def main():
    data = json.loads((DASHBOARD / "data/snapshot.json").read_text())
    handler = partial(SimpleHTTPRequestHandler, directory=str(DASHBOARD))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, sync_playwright() as playwright:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            browser = playwright.chromium.launch()
            errors = []
            url = f"http://127.0.0.1:{server.server_port}/"
            for width, height in [(1440, 940), (390, 844), (320, 720)]:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                expect(page.locator("#report")).to_be_visible()
                check_report(page, data)
                page.close()
            assert not errors, errors
            browser.close()
        finally:
            server.shutdown()
            thread.join()
    print("Desktop and mobile passed: sales, exact amounts, payments, alerts, marketing, coverage and filters.")


if __name__ == "__main__":
    main()
