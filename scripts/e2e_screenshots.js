// E2E screenshots against a running stack (http://localhost:3000).
// Usage: npm i playwright@1.57.0 (anywhere), then: node scripts/e2e_screenshots.js docs/screenshots
const { chromium } = require("playwright");
const out = process.argv[2];
const URL = "http://localhost:3000";
const log = (...a) => console.log(...a);

(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForSelector("canvas", { timeout: 20000 });
  await page.waitForTimeout(4000); // force layout settles
  await page.screenshot({ path: `${out}/01-graph.png` });
  log("graph ok");

  // Click a node: probe a grid over the graph canvas until the side panel shows a document.
  // Find a document node's screen position through the Sigma instance held in a React ref.
  const pos = await page.evaluate(() => {
    for (const el of document.querySelectorAll("div")) {
      const k = Object.keys(el).find((x) => x.startsWith("__reactFiber"));
      if (!k) continue;
      for (let f = el[k]; f; f = f.return) {
        for (let h = f.memoizedState; h && typeof h === "object" && "next" in h; h = h.next) {
          const v = h.memoizedState && h.memoizedState.current;
          if (v && typeof v.getNodeDisplayData === "function" && typeof v.graphToViewport === "function") {
            const g = v.getGraph();
            const node = g.nodes().filter((n) => n.startsWith("doc:")).sort((a, b) => g.degree(b) - g.degree(a))[0];
            const d = g.getNodeAttributes(node);
            const vp = v.graphToViewport({ x: d.x, y: d.y });
            const r = v.getContainer().getBoundingClientRect();
            return { x: r.left + vp.x, y: r.top + vp.y, node };
          }
        }
      }
    }
    return null;
  });
  if (!pos) throw new Error("sigma instance not found");
  await page.mouse.move(pos.x, pos.y);
  await page.waitForTimeout(300);
  await page.mouse.down(); await page.mouse.up();
  await page.waitForTimeout(800);
  const hit = await page.locator('aside[aria-label="Selection details"] article').count() > 0;
  if (!hit) throw new Error("no node hit");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}/02-node-panel.png` });
  log("panel ok:", await page.locator("#doc-title, #node-title").first().textContent());

  // If the clicked node is not a document, open one through search first.
  if (await page.getByRole("button", { name: "Why connected?" }).count() === 0) {
    log("clicked node is not a document; opening one via search");
    await page.keyboard.press("Meta+K");
    await page.getByRole("combobox", { name: "Search notes" }).or(page.locator('input[aria-label="Search notes"]')).first().fill("fermentation");
    await page.waitForTimeout(1500);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(2000);
  }
  await page.getByRole("button", { name: "Why connected?" }).first().click();
  await page.getByRole("dialog").waitFor();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/03-why-connected.png` });
  log("why ok");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // Search.
  await page.keyboard.press("Meta+K");
  await page.getByRole("dialog").waitFor();
  await page.getByRole("combobox", { name: "Search notes" }).or(page.locator('input[aria-label="Search notes"]')).first().fill("sourdough starter");
  await page.waitForSelector('[role="listbox"][aria-label="Search results"] [role="option"]', { timeout: 10000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/04-search.png` });
  log("search ok:", await page.locator('[role="option"]').count(), "results");
  await page.keyboard.press("Enter"); // opens the top hit in the local graph
  await page.waitForTimeout(2500);

  // Local graph, depth 2.
  const local = page.getByRole("group", { name: "Graph scope" }).getByRole("button", { name: "Local" });
  if ((await local.getAttribute("aria-pressed")) !== "true") await local.click();
  if (!(await page.locator('aside.filters').count())) await page.getByRole("button", { name: "Show filters" }).click();
  const slider = page.locator('aside.filters input[type="range"]').first();
  await slider.fill("2");
  await page.waitForTimeout(3500);
  await page.screenshot({ path: `${out}/05-local-depth2.png` });
  log("local ok:", await page.locator(".graph-status, .status").first().textContent().catch(() => ""));

  // Dark mode.
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}/06-dark-mode.png` });
  await page.getByRole("group", { name: "Graph scope" }).getByRole("button", { name: "Global" }).click();
  await page.waitForTimeout(3500);
  await page.screenshot({ path: `${out}/07-dark-global.png` });
  log("dark ok");

  log("page errors:", JSON.stringify(errors));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
