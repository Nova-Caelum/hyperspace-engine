#!/usr/bin/env node
// Browser checks for the console's round-1 features (row HSE-94), driven by
// probes/check_console_ui.py against a real loopback door. Launches system
// Chrome headless (never a downloaded browser), the same way
// probes/ui_page_check.mjs does.
//
//   runs     with no run on disk, the project page and the module page say
//            "No run open yet — the first step of new work is Understand.";
//            after one open and one closed run are written to disk, both pages
//            show the open run's goal and its step name, and not the closed run.
//   create   a task whose acceptance criteria are shorter than 20 characters is
//            refused, and the server's reason is on screen; a valid task and a
//            module are then created from the page and read back from the door.
//   worklog  on the Worklog tab: move a column by dragging, filter a column by a
//            value, hide a column, freeze a column and sort; after a reload every
//            setting still holds; the hidden column can then be shown again.
//
// Usage: node probes/ui_console_checks.mjs '<json config>'
//   config: {url, project_dir, project_code, project_name, module_name,
//            shots_dir?}
// Env:   PLAYWRIGHT_MODULE — path or specifier to import playwright from.
//
// Prints exactly one JSON line to stdout:
//   {ok, checks: {runs, create, worklog}, console_errors: [...]}
// where each check is {ok, steps: {<name>: <value>}, errors: [...]}.

import fs from "node:fs";
import path from "node:path";

const config = JSON.parse(process.argv[2] || "{}");
for (const key of ["url", "project_dir", "project_code", "project_name", "module_name"]) {
  if (!config[key]) {
    console.error(`ui_console_checks.mjs: config is missing "${key}"`);
    process.exit(2);
  }
}

const playwrightSpecifier = process.env.PLAYWRIGHT_MODULE || "playwright";
const imported = await import(playwrightSpecifier);
const chromium = imported.chromium ?? imported.default?.chromium;
if (!chromium) {
  console.error(`could not resolve a "chromium" export from ${playwrightSpecifier}`);
  process.exit(2);
}

const WAIT = 8000;
const CRITERIA_REASON = "acceptance_criteria must be 20-2000 characters";
const EMPTY_RUNS = "No run open yet — the first step of new work is Understand.";
const OPEN_RUN = { goal: "ship-console-round-one", status: "deciding", current_node: "deciding", step: "Decide" };
const CLOSED_RUN = { goal: "retired-console-experiment", status: "done", current_node: "executing" };
const DEFAULT_COLUMNS = ["date", "author", "summary", "tags", "surface", "client", "work_item"];

const consoleErrors = [];
const checks = {};
for (const name of ["runs", "create", "worklog"]) checks[name] = { ok: false, steps: {}, errors: [] };

function record(check, name, value) {
  checks[check].steps[name] = value;
  return value;
}

function fail(check, name, message) {
  checks[check].steps[name] = false;
  checks[check].errors.push(`${name}: ${message}`);
  throw new Error(`${name}: ${message}`);
}

function expect(check, name, condition, message) {
  if (!condition) fail(check, name, message);
  record(check, name, true);
}

async function shot(locator, file, bottom) {
  if (!config.shots_dir) return;
  try {
    fs.mkdirSync(config.shots_dir, { recursive: true });
    const target = path.join(config.shots_dir, file);
    if (bottom) {
      // Crop from the top of `locator` down to the bottom of `bottom`: the feature, not the empty pane.
      const top = await locator.boundingBox();
      const end = await bottom.boundingBox();
      await locator.page().screenshot({ path: target, animations: "disabled",
        clip: { x: top.x, y: top.y, width: top.width, height: end.y + end.height - top.y + 12 } });
    } else {
      await locator.screenshot({ path: target, animations: "disabled" });
    }
  } catch (e) {
    consoleErrors.push(`screenshot ${file} failed: ${e.message.split("\n")[0]}`);
  }
}

async function readJson(urlPath) {
  const response = await fetch(new URL(urlPath, config.url));
  if (!response.ok) throw new Error(`GET ${urlPath} → ${response.status}`);
  return response.json();
}

function writeRun(run) {
  const folder = path.join(config.project_dir, "hyperspace", "runs", run.goal);
  fs.mkdirSync(folder, { recursive: true });
  fs.writeFileSync(
    path.join(folder, "loop.state.json"),
    JSON.stringify({ goal_slug: run.goal, status: run.status, current_node: run.current_node }, null, 2),
  );
}

async function openProject(page) {
  await page.goto(config.url, { waitUntil: "networkidle" });
  // The console restores the last selection; with a single project it selects it.
  await page.getByRole("heading", { name: config.project_name, exact: true }).first()
    .waitFor({ state: "visible", timeout: WAIT });
}

async function openModule(page) {
  await page.getByRole("button", { name: `Open ${config.module_name}`, exact: true }).first().click({ timeout: WAIT });
  const drawer = page.getByRole("dialog").filter({ hasText: config.module_name }).first();
  await drawer.waitFor({ state: "visible", timeout: WAIT });
  return drawer;
}

async function closeDrawer(page) {
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
}

// ── runs ────────────────────────────────────────────────────────────────────

async function checkRunsEmpty(page) {
  await openProject(page);
  const projectRuns = page.locator('[data-open-runs="project"]');
  await projectRuns.waitFor({ state: "visible", timeout: WAIT }).catch(() => fail("runs", "project_empty_state", "no Open runs section on the project page"));
  expect("runs", "project_empty_state", await projectRuns.getByText(EMPTY_RUNS, { exact: true }).isVisible(),
    `the project page does not say "${EMPTY_RUNS}"`);
  const drawer = await openModule(page);
  const moduleRuns = drawer.locator('[data-open-runs="module"]');
  await moduleRuns.waitFor({ state: "visible", timeout: WAIT }).catch(() => fail("runs", "module_empty_state", "no Open runs section on the module page"));
  expect("runs", "module_empty_state", await moduleRuns.getByText(EMPTY_RUNS, { exact: true }).isVisible(),
    `the module page does not say "${EMPTY_RUNS}"`);
  await closeDrawer(page);
}

async function checkRunsOpen(page) {
  writeRun(OPEN_RUN);
  writeRun(CLOSED_RUN);
  const listed = await readJson(`/api/projects/${encodeURIComponent(config.project_code)}/runs`);
  record("runs", "door_lists_both_runs", listed.map(r => `${r.goal}:${r.open ? "open" : "closed"}`));

  await page.reload({ waitUntil: "networkidle" });
  await openProject(page);
  const projectRuns = page.locator('[data-open-runs="project"]');
  await projectRuns.getByText(OPEN_RUN.goal, { exact: true }).waitFor({ state: "visible", timeout: WAIT })
    .catch(() => fail("runs", "project_open_run", `the open run "${OPEN_RUN.goal}" is not on the project page`));
  record("runs", "project_open_run", true);
  const projectText = (await projectRuns.innerText()).replace(/\s+/g, " ");
  expect("runs", "project_step_name", projectText.includes(OPEN_RUN.step), `step "${OPEN_RUN.step}" not shown: ${projectText}`);
  expect("runs", "project_hides_closed_run", !projectText.includes(CLOSED_RUN.goal), `closed run shown: ${projectText}`);
  expect("runs", "project_empty_state_gone", !projectText.includes("No run open yet"), "the empty sentence is still shown");
  await shot(projectRuns, "open-runs-project.png");

  const drawer = await openModule(page);
  const moduleRuns = drawer.locator('[data-open-runs="module"]');
  await moduleRuns.getByText(OPEN_RUN.goal, { exact: true }).waitFor({ state: "visible", timeout: WAIT })
    .catch(() => fail("runs", "module_open_run", `the open run "${OPEN_RUN.goal}" is not on the module page`));
  record("runs", "module_open_run", true);
  const moduleText = (await moduleRuns.innerText()).replace(/\s+/g, " ");
  expect("runs", "module_step_name", moduleText.includes(OPEN_RUN.step), `step "${OPEN_RUN.step}" not shown: ${moduleText}`);
  expect("runs", "module_hides_closed_run", !moduleText.includes(CLOSED_RUN.goal), `closed run shown: ${moduleText}`);
  await shot(moduleRuns, "open-runs-module.png");
  await closeDrawer(page);
}

// ── create ──────────────────────────────────────────────────────────────────

async function openCreate(page, kind, title) {
  await page.getByRole("button", { name: "Add new", exact: true }).click({ timeout: WAIT });
  await page.getByRole("menuitem", { name: kind, exact: true }).click({ timeout: WAIT });
  const dialog = page.getByRole("dialog", { name: title, exact: true });
  await dialog.waitFor({ state: "visible", timeout: WAIT });
  return dialog;
}

async function checkCreate(page) {
  await openProject(page);
  const badTitle = "Console check task";
  const dialog = await openCreate(page, "Task", "New Task");
  await dialog.getByLabel("Title", { exact: true }).fill(badTitle);
  await dialog.getByLabel("Acceptance Criteria", { exact: true }).fill("too short");
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  // What the page said, whatever it said — the RED run's evidence of a swallowed reason.
  await page.locator("[data-sonner-toast]").first().waitFor({ state: "visible", timeout: WAIT }).catch(() => {});
  const toasts = await page.locator("[data-sonner-toast]").allInnerTexts().catch(() => []);
  record("create", "toasts_on_screen", toasts.map(text => text.replace(/\s+/g, " ").trim()));
  const reason = page.getByText(CRITERIA_REASON, { exact: false }).first();
  await reason.waitFor({ state: "visible", timeout: WAIT })
    .catch(() => fail("create", "failure_reason_on_screen", `"${CRITERIA_REASON}" never appeared on screen`));
  record("create", "failure_reason_on_screen", (await reason.innerText()).trim());
  const errorSurface = page.locator("[data-failure]").filter({ hasText: CRITERIA_REASON }).first();
  if (await errorSurface.count()) await shot(errorSurface, "error-message.png");
  expect("create", "dialog_kept_draft", (await dialog.getByLabel("Title", { exact: true }).inputValue()) === badTitle,
    "the failed create lost the typed title");

  await dialog.getByLabel("Acceptance Criteria", { exact: true }).fill("The task appears in the project's task list after it is created.");
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await dialog.waitFor({ state: "detached", timeout: WAIT })
    .catch(() => fail("create", "task_created", "the valid create did not close the dialog"));
  await page.getByText(badTitle, { exact: true }).first().waitFor({ state: "visible", timeout: WAIT })
    .catch(() => fail("create", "task_created", "the created task is not in the list"));
  const items = await readJson(`/api/projects/${encodeURIComponent(config.project_code)}/work-items`);
  expect("create", "task_created", items.some(row => row.name === badTitle), "the door has no such task");

  const moduleName = "Console check module";
  const moduleDialog = await openCreate(page, "Module", "New Module");
  await moduleDialog.getByLabel("Name", { exact: true }).fill(moduleName);
  await moduleDialog.getByRole("button", { name: "Create", exact: true }).click();
  await moduleDialog.waitFor({ state: "detached", timeout: WAIT })
    .catch(() => fail("create", "module_created", "the module create did not close the dialog"));
  await page.getByText(moduleName, { exact: true }).first().waitFor({ state: "visible", timeout: WAIT })
    .catch(() => fail("create", "module_created", "the created module is not in the list"));
  const modules = await readJson(`/api/projects/${encodeURIComponent(config.project_code)}/modules`);
  expect("create", "module_created", modules.some(row => row.name === moduleName), "the door has no such module");
}

// ── worklog ─────────────────────────────────────────────────────────────────

async function openWorklog(page) {
  await page.getByRole("tab", { name: "Worklog", exact: true }).click({ timeout: WAIT });
  const table = page.locator("[data-worklog-table]");
  await table.waitFor({ state: "visible", timeout: WAIT });
  await page.locator("tr[data-worklog-row]").first().waitFor({ state: "visible", timeout: WAIT });
  return table;
}

async function tableState(page) {
  return page.evaluate(() => {
    const table = document.querySelector("[data-worklog-table]");
    const heads = [...table.querySelectorAll("thead th[data-column]")];
    const frozen = heads.filter(th => th.dataset.frozen === "true");
    return {
      columns: heads.map(th => th.dataset.column),
      frozen: frozen.map(th => th.dataset.column),
      frozen_sticky: frozen.map(th => `${getComputedStyle(th).position}@${getComputedStyle(th).left}`),
      sort: heads.filter(th => ["ascending", "descending"].includes(th.getAttribute("aria-sort")))
        .map(th => `${th.dataset.column}:${th.getAttribute("aria-sort")}`),
      filtered: heads.filter(th => th.dataset.filtered === "true").map(th => th.dataset.column),
      rows: [...table.querySelectorAll("tr[data-worklog-row]")].map(tr => tr.dataset.worklogRow),
    };
  });
}

async function columnMenu(page, label, item) {
  await page.getByRole("button", { name: `Column options: ${label}`, exact: true }).click({ timeout: WAIT });
  await page.getByRole("menuitem", { name: item, exact: true }).click({ timeout: WAIT });
}

async function checkWorklog(page) {
  await openProject(page);
  await openWorklog(page).catch(() => fail("worklog", "tab_opens", "no Worklog tab with a table of entries"));
  record("worklog", "tab_opens", true);
  const initial = await tableState(page);
  record("worklog", "initial", initial);
  expect("worklog", "defaults", JSON.stringify(initial.columns) === JSON.stringify(DEFAULT_COLUMNS)
    && initial.frozen.length === 0 && initial.sort.length === 0 && initial.filtered.length === 0,
  `unexpected default layout ${JSON.stringify(initial)}`);
  expect("worklog", "seeded_rows", initial.rows.length >= 4, `expected the 4 seeded entries, saw ${initial.rows.length}`);

  // 1. Move: drag the Surface header onto the Author header.
  await page.locator('thead th[data-column="surface"]').dragTo(page.locator('thead th[data-column="author"]'));
  const moved = await tableState(page);
  expect("worklog", "moved_by_drag", moved.columns.indexOf("surface") < moved.columns.indexOf("author"),
    `dragging Surface onto Author left ${JSON.stringify(moved.columns)}`);

  // 2. Filter: keep only the "designer" author.
  await page.getByRole("button", { name: "Filter: Author", exact: true }).click({ timeout: WAIT });
  await page.getByRole("checkbox", { name: "designer", exact: true }).click({ timeout: WAIT });
  await page.keyboard.press("Escape");
  const filtered = await tableState(page);
  expect("worklog", "filtered_by_value", filtered.filtered.includes("author") && filtered.rows.length === 2
    && filtered.rows.length < initial.rows.length, `author filter left ${filtered.rows.length} rows`);

  // 3. Hide the Client column.
  await columnMenu(page, "Client", "Hide column");
  // 4. Freeze the Summary column.
  await columnMenu(page, "Summary", "Freeze column");
  // 5. Sort by date, oldest first.
  await columnMenu(page, "Date", "Sort ascending");

  const before = await tableState(page);
  record("worklog", "before_reload", before);
  expect("worklog", "hidden", !before.columns.includes("client"), "Client is still shown");
  expect("worklog", "frozen", before.frozen.join() === "summary" && /^sticky@\d/.test(before.frozen_sticky.join()),
    `frozen ${JSON.stringify(before.frozen)} / ${JSON.stringify(before.frozen_sticky)}`);
  expect("worklog", "sorted", before.sort.join() === "date:ascending", `sort ${JSON.stringify(before.sort)}`);

  await page.reload({ waitUntil: "networkidle" });
  await openProject(page);
  await openWorklog(page);
  const after = await tableState(page);
  record("worklog", "after_reload", after);
  expect("worklog", "survives_reload", JSON.stringify(after) === JSON.stringify(before),
    `layout changed across the reload: ${JSON.stringify(before)} → ${JSON.stringify(after)}`);
  await shot(page.locator("[data-worklog-panel]"), "worklog-after-reload.png", page.locator("[data-worklog-table]"));

  // Frozen means it stays put: scroll the table sideways and measure.
  const geometry = await page.evaluate(() => {
    const table = document.querySelector("[data-worklog-table]");
    const scroller = table.parentElement;
    const frozenTh = table.querySelector('thead th[data-frozen="true"]');
    const otherTh = table.querySelector('thead th[data-column]:not([data-frozen])');
    const x = el => el.getBoundingClientRect().left;
    const before = { frozen: x(frozenTh), other: x(otherTh) };
    scroller.scrollLeft = 240;
    const after = { frozen: x(frozenTh), other: x(otherTh), scrolled: scroller.scrollLeft };
    scroller.scrollLeft = 0;
    return { before, after };
  });
  record("worklog", "frozen_geometry", geometry);
  expect("worklog", "frozen_stays_put", geometry.after.scrolled > 0
    && Math.abs(geometry.after.frozen - geometry.before.frozen) < 1
    && geometry.before.other - geometry.after.other > 100,
  `scrolling sideways moved the frozen column or nothing scrolled: ${JSON.stringify(geometry)}`);

  // Re-show the hidden column from the Columns menu.
  await page.getByRole("button", { name: "Show or hide columns", exact: true }).click({ timeout: WAIT });
  const clientItem = page.getByRole("menuitemcheckbox", { name: "Client", exact: true });
  await clientItem.waitFor({ state: "visible", timeout: WAIT });
  expect("worklog", "hidden_listed_unchecked", (await clientItem.getAttribute("aria-checked")) === "false",
    "the Columns menu does not list Client as hidden");
  await page.waitForTimeout(300);
  await shot(page.locator("[data-worklog-panel]"), "worklog-columns-menu.png", page.getByRole("menu").first());
  await clientItem.click({ timeout: WAIT });
  await page.keyboard.press("Escape");
  const reshown = await tableState(page);
  expect("worklog", "reshown", reshown.columns.includes("client"), "Client did not come back");
}

// ── run everything ──────────────────────────────────────────────────────────

let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("pageerror", (e) => consoleErrors.push(String(e.message ?? e)));
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

  for (const [name, run] of [
    ["runs", checkRunsEmpty],
    ["create", checkCreate],
    ["worklog", checkWorklog],
    ["runs", checkRunsOpen],
  ]) {
    if (checks[name].errors.length) continue; // an earlier half of this check already failed
    try {
      await run(page);
    } catch (e) {
      if (!checks[name].errors.length) checks[name].errors.push(e.message.split("\n")[0]);
    }
  }
  for (const check of Object.values(checks)) check.ok = check.errors.length === 0;
} catch (e) {
  consoleErrors.push(`fatal: ${e.message}`);
} finally {
  if (browser) await browser.close();
}

const ok = Object.values(checks).every(c => c.ok);
console.log(JSON.stringify({ ok, checks, console_errors: consoleErrors }));
process.exit(ok ? 0 : 1);
