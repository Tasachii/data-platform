"use strict";

const byId = id => document.getElementById(id);
const sum = (rows, field) => rows.reduce((total, row) => total + row[field], 0);
const number = new Intl.NumberFormat("en-GB");
const baht = new Intl.NumberFormat("en-GB", {
  style: "currency", currency: "THB", currencyDisplay: "narrowSymbol"
});
const money = satang => baht.format(satang / 100);
const shortDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const dateRange = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const range = (start, end) => dateRange.formatRange(new Date(start + "T00:00:00Z"), new Date(end + "T00:00:00Z"));
const day = iso => shortDate.format(new Date(iso + "T00:00:00Z"));
const labels = {
  web: "Web store", shopee: "Shopee", lazada: "Lazada", facebook: "Facebook",
  google: "Google", tiktok: "TikTok", organic: "Organic", CRITICAL: "Critical", WARNING: "Warning",
  match_rate: "Low match rate", net_difference: "Settlement gap", duplicate_posting: "Duplicate posting"
};

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function groups(rows, field) {
  const result = new Map();
  for (const row of rows) {
    if (!result.has(row[field])) result.set(row[field], []);
    result.get(row[field]).push(row);
  }
  return result;
}

function period(rows) {
  if (!rows.length) return "No dates covered";
  const dates = rows.map(row => row.date).sort();
  return range(dates[0], dates.at(-1));
}

function table(headers, values) {
  const grid = element("table");
  const head = grid.createTHead().insertRow();
  for (const name of headers) {
    const cell = element("th", name);
    cell.scope = "col";
    head.append(cell);
  }
  const body = grid.createTBody();
  for (const valuesRow of values) {
    const row = body.insertRow();
    for (const value of valuesRow) {
      const cell = row.insertCell();
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value;
    }
  }
  return grid;
}

function pair(label, value, className) {
  const line = element("div", undefined, className);
  line.append(element("span", label), element("strong", value));
  return line;
}

function rail(fraction) {
  const track = element("div", undefined, "rail");
  const fill = element("i");
  fill.style.width = (fraction * 100) + "%";
  track.setAttribute("aria-hidden", "true");
  track.append(fill);
  return track;
}

function drawTrend(daily) {
  const plot = element("div", undefined, "plot");
  const axis = pair(day(daily[0].date), day(daily.at(-1).date), "axis");
  const peak = Math.max(...daily.map(r => r.net));
  let active;
  function inspect(button, row) {
    if (active) active.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-pressed", "true");
    active = button;
    byId("inspect").textContent = day(row.date) + " · " + money(row.net) + " · " + number.format(row.orders) + " net orders";
  }
  let keyboardTarget;
  function setKeyboardTarget(button) {
    if (keyboardTarget) keyboardTarget.tabIndex = -1;
    keyboardTarget = button;
    button.tabIndex = 0;
  }
  for (const row of daily) {
    const button = element("button");
    button.type = "button";
    button.tabIndex = -1;
    button.setAttribute("aria-label", day(row.date) + ", " + money(row.net));
    button.setAttribute("aria-pressed", "false");
    const bar = element("i");
    bar.style.height = (peak ? 100 * row.net / peak : 0) + "%";
    button.append(bar);
    button.addEventListener("click", () => inspect(button, row));
    button.addEventListener("focus", () => {
      inspect(button, row);
      setKeyboardTarget(button);
    });
    button.addEventListener("keydown", event => {
      const target = {
        ArrowLeft: button.previousElementSibling, ArrowRight: button.nextElementSibling,
        Home: plot.firstElementChild, End: plot.lastElementChild
      }[event.key];
      if (target) {
        event.preventDefault();
        target.focus();
      }
    });
    button.addEventListener("pointerenter", () => inspect(button, row));
    plot.append(button);
    if (row.net === peak && !active) {
      inspect(button, row);
      setKeyboardTarget(button);
    }
  }
  const scale = element("div", undefined, "y-scale");
  const compact = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });
  for (const tick of [1, 0.5, 0]) scale.append(element("span", "฿" + compact.format(peak * tick / 100)));
  const graph = element("div", undefined, "trend-graph");
  graph.append(scale, plot);
  byId("trend").replaceChildren(graph, axis);
  byId("sales-table").replaceChildren(table(["Bangkok date", "Net orders", "Net revenue", "Refunds"],
    daily.map(r => [r.date, number.format(r.orders), money(r.net), money(r.refunds)])));
}

function renderSales(rows) {
  const selected = byId("channel").value;
  const filtered = rows.filter(r => selected === "all" || selected === r.channel);
  const net = sum(filtered, "net");
  const refunds = sum(filtered, "refunds");
  const bahtValue = net / 100;
  const inMillions = Math.abs(bahtValue) >= 1_000_000;
  byId("net").textContent = inMillions ? (bahtValue / 1_000_000).toFixed(2) : number.format(bahtValue);
  byId("net-unit").textContent = inMillions ? "million baht" : "baht";
  byId("sales-scope").textContent = "Daily sales · Bangkok · " + period(filtered);
  byId("ledger").replaceChildren(pair("Gross sales", money(net + refunds), "ledger-line"),
    pair("Refunds", money(refunds), "ledger-line"), pair("Net revenue", money(net), "ledger-line net-total"),
    pair("Net orders", number.format(sum(filtered, "orders")), "ledger-line"));
  const channels = byId("channels");
  channels.replaceChildren();
  const allNet = sum(rows, "net");
  const totals = [...groups(rows, "channel")].map(([key, values]) => [key, sum(values, "net")]);
  for (const [key, value] of totals.sort((a, b) => b[1] - a[1])) {
    const share = allNet ? value / allNet : 0;
    channels.append(pair(labels[key], (share * 100).toFixed(1) + "%", "channel-label"), rail(share));
  }
  const daily = [...groups(filtered, "date")].map(([date, values]) => ({
    date, net: sum(values, "net"), orders: sum(values, "orders"), refunds: sum(values, "refunds")
  }));
  if (daily.length) drawTrend(daily);
  else {
    byId("trend").textContent = "No sales for this selection.";
    byId("inspect").replaceChildren();
    byId("sales-table").replaceChildren();
  }
}

function renderPayments(rows, alerts) {
  const total = sum(rows, "gateway");
  const rate = total ? (sum(rows, "matched") / total * 100).toFixed(2) + "% matched" : "Match rate unavailable";
  byId("recon-scope").textContent = rows.length ? period(rows) + " · " + number.format(total) + " gateway transactions · " + rate : "Outside settlement coverage";
  const gaps = byId("gaps");
  gaps.replaceChildren();
  const scale = Math.max(1, ...rows.map(r => Math.abs(r.gap)));
  for (const row of rows) {
    const line = element("div", undefined, "gap-line");
    const track = element("div", undefined, "gap-track");
    const bar = element("i");
    const width = 50 * Math.abs(row.gap) / scale;
    bar.style.width = width + "%";
    bar.style.left = (row.gap < 0 ? 50 - width : 50) + "%";
    if (row.gap < 0) bar.className = "negative";
    track.append(bar);
    line.append(element("span", day(row.date)), track, element("strong", money(row.gap)));
    gaps.append(line);
  }
  if (rows.length) {
    const legend = element("div", undefined, "gap-legend");
    legend.append(element("span", "Ledger higher"), element("span", "Gateway higher"));
    gaps.prepend(legend);
  }
  if (!rows.length) gaps.append(element("p", "No settlement files cover this window.", "empty"));
  const severity = byId("severity").value;
  const filtered = alerts.filter(r => severity === "all" || r.severity === severity);
  const panel = byId("alerts");
  panel.replaceChildren();
  panel.append(element("div", String(sum(filtered, "alerts")), "metric summary-stat"));
  if (!filtered.length) panel.append(element("p", rows.length ? "No alerts match this selection." : "No settlement days to evaluate.", "note"));
  for (const [rule, records] of groups(filtered, "rule")) {
    const line = pair(labels[rule], number.format(sum(records, "alerts")), "alert-line");
    line.firstChild.prepend(element("span", labels[records[0].severity] + " · ",
      "severity " + records[0].severity.toLowerCase()));
    panel.append(line, rail(sum(records, "alerts") / sum(filtered, "alerts")));
  }
  byId("alert-table").replaceChildren(filtered.length ? table(["UTC date", "Severity", "Rule"],
    filtered.map(r => [r.date, labels[r.severity], labels[r.rule]])) : element("p", "No alert dates in this selection.", "note"));
}

function renderMarketing(rows) {
  const paid = rows.filter(r => r.platform !== "organic");
  const spend = sum(paid, "spend");
  const roas = (revenue, expense) => expense ? (revenue / expense).toFixed(2) + "×" : "—";
  byId("marketing-scope").textContent = rows.length ? period(rows) + " · Paid-channel ROAS " + roas(sum(paid, "revenue"), spend) : "Outside attribution coverage";
  const panel = byId("marketing");
  if (!rows.length) {
    panel.replaceChildren(element("p", "No marketing activity covers this window.", "empty"));
    return;
  }
  const platforms = [...groups(rows, "platform")].map(([key, items]) => ({
    key, revenue: sum(items, "revenue"), orders: sum(items, "orders"), spend: sum(items, "spend")
  })).sort((a, b) => b.revenue - a.revenue);
  const peak = platforms[0].revenue;
  const headers = ["Source", "Credited revenue", "Ad spend", "Net orders", "ROAS"];
  const grid = table(headers, platforms.map(row => {
    const revenue = element("div", undefined, "credited");
    revenue.append(element("strong", money(row.revenue)), rail(peak ? row.revenue / peak : 0));
    return [labels[row.key], revenue, money(row.spend), number.format(row.orders), roas(row.revenue, row.spend)];
  }));
  // Narrow screens stack each source's measures. Keep the same values and column headers.
  for (const row of grid.tBodies[0].rows) {
    for (const cell of Array.from(row.cells).slice(1)) {
      const label = element("span", headers[cell.cellIndex], "mobile-label");
      label.setAttribute("aria-hidden", "true");
      cell.prepend(label);
    }
  }
  const scroll = element("div", undefined, "scroll");
  scroll.append(grid);
  panel.replaceChildren(scroll);
}

function start(data) {
  if (data.version !== 1 || data.synthetic !== true || data.moneyUnit !== "satang") {
    throw new Error("Unsupported snapshot");
  }
  const channel = byId("channel");
  channel.add(new Option("All channels", "all"));
  for (const key of groups(data.sales, "channel").keys()) channel.add(new Option(labels[key], key));
  const feedNames = { orders: "Orders", gateway_txns: "Payments", ad_performance: "Ad spend" };
  for (const [feed, label] of Object.entries(feedNames)) {
    const coverage = data.coverage.find(row => row.feed === feed);
    if (!coverage) continue;
    const item = element("div");
    const description = element("dd", range(coverage.start, coverage.finish));
    item.append(element("dt", label + " · " + coverage.days + " source days"), description);
    byId("coverage").append(item);
  }
  const dates = [...new Set([...data.sales, ...data.reconciliation, ...data.marketing].map(r => r.date))].sort();
  const shift = (iso, count) => new Date(Date.parse(iso + "T00:00:00Z") + count * 86400000).toISOString().slice(0, 10);
  function render() {
    const window = byId("window").value;
    const end = window === "first" ? shift(dates[0], 6) : dates.at(-1);
    const start = ["all", "first"].includes(window) ? dates[0] : shift(end, 1 - Number(window));
    const within = r => r.date >= start && r.date <= end;
    renderSales(data.sales.filter(within));
    renderPayments(data.reconciliation.filter(within), data.alerts.filter(within));
    renderMarketing(data.marketing.filter(within));
    byId("status").textContent = range(start, end) + "   ·   Thai baht (THB)";
  }
  for (const id of ["window", "channel", "severity"]) byId(id).addEventListener("change", render);
  render();
  byId("report").hidden = false;
  byId("window").disabled = false;
}

fetch("data/snapshot.json").then(response => {
  if (!response.ok) throw new Error("Snapshot unavailable");
  return response.json();
}).then(start).catch(() => {
  byId("status").textContent = "The snapshot could not be loaded. Refresh the page to retry.";
});
