/*
 * Narrow-viewport (iPhone ~390 px) check of the real Learning Center panel.
 *
 * Usage:
 *   python scripts/learning_center_fixtures.py /tmp/lc.json
 *   NODE_PATH="$(npm root -g)" node scripts/check_learning_center_mobile.cjs /tmp/lc.json [screenshot-dir]
 *
 * Renders custom_components/homeintent/frontend/homeintent-learning-center.js
 * in Chromium with a mocked `hass.connection` that answers with REAL backend
 * responses (fixture file), in light and dark theme, and asserts: no
 * horizontal page overflow, reachable destructive buttons, >=44 px touch
 * targets, a usable modal and readable (non-transparent) text.
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const fixtures = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const shots = process.argv[3];
const js = fs.readFileSync(path.join(__dirname, "..", "custom_components", "homeintent", "frontend", "homeintent-learning-center.js"), "utf-8");

const THEMES = {
  light: { "--primary-background-color": "#fafafa", "--card-background-color": "#ffffff", "--primary-text-color": "#212121", "--secondary-text-color": "#727272", "--primary-color": "#03a9f4", "--divider-color": "rgba(0,0,0,.12)" },
  dark: { "--primary-background-color": "#111111", "--card-background-color": "#1c1c1c", "--primary-text-color": "#e1e1e1", "--secondary-text-color": "#9b9b9b", "--primary-color": "#ff9800", "--divider-color": "rgba(225,225,225,.12)", "--app-header-background-color": "#101e24" },
};

function page_html(theme) {
  const vars = Object.entries(THEMES[theme]).map(([k, v]) => `${k}: ${v};`).join(" ");
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>html,body{margin:0;height:100%;} homeintent-learning-center{ ${vars} }</style></head>
<body><homeintent-learning-center></homeintent-learning-center></body></html>`;
}

async function check(browser, theme, failures) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "de-DE" });
  const page = await context.newPage();
  page.on("pageerror", (err) => failures.push(`${theme}: page error ${err.message}`));
  page.on("console", (msg) => { if (msg.type() === "error") failures.push(`${theme}: console ${msg.text()}`); });
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (url.startsWith("http://panel.local/")) return route.continue();
    failures.push(`${theme}: unexpected network request ${url}`);
    return route.abort();
  });
  await page.route("http://panel.local/", (route) => route.fulfill({ contentType: "text/html", body: page_html(theme) }));
  await page.goto("http://panel.local/");
  await page.evaluate(({ fixtures }) => {
    window.__sent = [];
    const answer = (msg) => {
      window.__sent.push(msg);
      const type = msg.type.replace("homeintent/learning_center/", "");
      const key = msg.ref ? `${type}:${msg.ref}` : type;
      if (key in fixtures) return Promise.resolve(JSON.parse(JSON.stringify(fixtures[key])));
      if (type === "models/forget") return Promise.resolve({ forgotten: true });
      return Promise.reject({ code: "not_found" });
    };
    window.__hass = {
      language: "de", locale: { language: "de", time_zone: "server" }, config: { time_zone: "Europe/Berlin" },
      connection: { sendMessagePromise: answer, subscribeMessage: async () => () => {}, addEventListener: () => {} },
    };
  }, { fixtures });
  await page.addScriptTag({ content: js, type: "module" });
  await page.evaluate(() => {
    const el = document.querySelector("homeintent-learning-center");
    el.narrow = true;
    el.route = { prefix: "/homeintent", path: "" };
    el.hass = window.__hass;
  });
  const root = () => page.locator("homeintent-learning-center");
  const settle = () => page.waitForTimeout(250);
  const assertLayout = async (label) => {
    const result = await page.evaluate(() => {
      const host = document.querySelector("homeintent-learning-center");
      const sr = host.shadowRoot;
      const content = sr.querySelector(".content");
      const small = [];
      for (const el of sr.querySelectorAll("button, a.button, input, select, summary")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const minimum = el.classList.contains("chip") ? 36 : 44;
        if (r.height < minimum - 0.5) small.push(`${el.className || el.tagName}:${Math.round(r.height)}`);
      }
      const overflowing = [];
      for (const el of sr.querySelectorAll(".card, .row, .card-title, .toolbar")) {
        const r = el.getBoundingClientRect();
        if (r.right > window.innerWidth + 0.5) overflowing.push(el.className);
      }
      const styles = getComputedStyle(sr.querySelector(".card") || host);
      return {
        pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
        contentOverflow: content ? content.scrollWidth - content.clientWidth : 0,
        small, overflowing, color: styles.color, background: styles.backgroundColor,
      };
    });
    if (result.pageOverflow > 0) failures.push(`${theme}/${label}: page overflows by ${result.pageOverflow}px`);
    if (result.contentOverflow > 0) failures.push(`${theme}/${label}: content overflows by ${result.contentOverflow}px`);
    if (result.small.length) failures.push(`${theme}/${label}: touch targets below minimum ${result.small.join(", ")}`);
    if (result.overflowing.length) failures.push(`${theme}/${label}: elements beyond viewport ${result.overflowing.join(", ")}`);
    if (result.color === result.background) failures.push(`${theme}/${label}: text invisible`);
    if (shots) await page.screenshot({ path: path.join(shots, `lc-${theme}-${label}.png`), fullPage: false });
    return result;
  };
  await settle();
  await assertLayout("overview");
  await root().locator('button[role="tab"]', { hasText: "Wissen" }).click();
  await settle();
  await assertLayout("knowledge");
  // Detail with the very long entity id.
  const longCard = root().locator(".model-card", { hasText: "sehr_langer" }).first();
  if (await longCard.count()) {
    await longCard.click();
    await settle();
    await assertLayout("detail-long-id");
    await root().locator(".back").click();
    await settle();
  } else failures.push(`${theme}: long-id card missing`);
  await root().locator(".model-card", { hasText: "Morgenroutine" }).filter({ hasNotText: "Persönlich" }).first().click();
  await settle();
  await root().locator("button", { hasText: "Woher weißt du das?" }).click();
  await settle();
  await root().locator("details summary").click();
  await settle();
  await assertLayout("detail-habit");
  const forget = root().locator("button.danger", { hasText: "Modell vergessen" });
  if (!(await forget.isVisible())) failures.push(`${theme}: forget button not reachable`);
  await forget.scrollIntoViewIfNeeded();
  await forget.click();
  await settle();
  const dialog = root().locator('[role="alertdialog"]');
  if (!(await dialog.isVisible())) failures.push(`${theme}: confirmation dialog not visible`);
  const box = await dialog.boundingBox();
  if (!box || box.width > 390 || box.x < 0) failures.push(`${theme}: dialog wider than viewport`);
  await assertLayout("dialog");
  await page.keyboard.press("Escape");
  await settle();
  if (await dialog.count()) failures.push(`${theme}: Escape did not close dialog`);
  await root().locator('button[role="tab"]', { hasText: "Autonomie" }).click();
  await settle();
  await assertLayout("autonomy");
  await root().locator('button[role="tab"]', { hasText: "Aktivität" }).click();
  await settle();
  await assertLayout("activity");
  const sent = await page.evaluate(() => window.__sent);
  if (sent.some((msg) => "user_id" in msg)) failures.push(`${theme}: browser sent a user_id`);
  if (sent.some((msg) => msg.type.endsWith("models/forget"))) failures.push(`${theme}: forget sent without confirmation`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  const failures = [];
  for (const theme of ["light", "dark"]) await check(browser, theme, failures);
  await browser.close();
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exit(1);
  }
  console.log("Learning Center mobile check passed (390x844, light + dark).");
})();
