#!/usr/bin/env node
// Runtime fetch check for the shipped console bundle. Launches system Chrome
// headless (never a downloaded browser), opens the page, waits for network
// idle, asserts the DOM shows a seeded project's name, clicks into it,
// asserts a seeded work-item name is visible, and records every request URL
// whose path starts with /api/ or /mcp — the empirical proof that the
// bundle's relative VITE_API_BASE_URL resolved to the same origin the page
// was served from, rather than an absolute host or the in-memory mock.
//
// Usage: node probes/ui_page_check.mjs <url> [projectName] [itemName]
// Env:   PLAYWRIGHT_MODULE — path or specifier to import playwright from
//        (defaults to the bare "playwright" specifier). Pass the caelos
//        build dir's node_modules/playwright/index.mjs so this script never
//        needs its own node_modules — the same convention Caelos's own
//        tests/browser.mjs uses for PLAYWRIGHT_MODULE.
//
// Prints exactly one JSON line to stdout:
//   {ok, project_seen, item_seen, api_requests: [...], console_errors: [...]}

const url = process.argv[2];
const projectName = process.argv[3] || "Hyperspace Bundle Check";
const itemName = process.argv[4] || "Bundle check task";

if (!url) {
  console.error("usage: node probes/ui_page_check.mjs <url> [projectName] [itemName]");
  process.exit(2);
}

const playwrightSpecifier = process.env.PLAYWRIGHT_MODULE || "playwright";
const imported = await import(playwrightSpecifier);
const chromium = imported.chromium ?? imported.default?.chromium;
if (!chromium) {
  console.error(`could not resolve a "chromium" export from ${playwrightSpecifier}`);
  process.exit(2);
}

const apiRequests = [];
const consoleErrors = [];
let ok = false;
let projectSeen = false;
let itemSeen = false;

let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  page.on("request", (req) => {
    try {
      const u = new URL(req.url());
      if (u.pathname.startsWith("/api/") || u.pathname === "/mcp") {
        apiRequests.push(req.url());
      }
    } catch {
      // ignore unparsable request URLs
    }
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e.message ?? e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  await page.goto(url, { waitUntil: "networkidle" });

  projectSeen = await page
    .getByText(projectName, { exact: false })
    .first()
    .isVisible()
    .catch(() => false);

  if (projectSeen) {
    try {
      await page.getByText(projectName, { exact: false }).first().click({ timeout: 5000 });
      await page.waitForLoadState("networkidle");
    } catch (e) {
      consoleErrors.push(`click into project failed: ${e.message}`);
    }
  }

  itemSeen = await page
    .getByText(itemName, { exact: false })
    .first()
    .isVisible()
    .catch(() => false);

  ok = projectSeen && itemSeen;
} catch (e) {
  consoleErrors.push(`fatal: ${e.message}`);
  ok = false;
} finally {
  if (browser) await browser.close();
}

console.log(
  JSON.stringify({
    ok,
    project_seen: projectSeen,
    item_seen: itemSeen,
    api_requests: apiRequests,
    console_errors: consoleErrors,
  })
);

process.exit(ok ? 0 : 1);
