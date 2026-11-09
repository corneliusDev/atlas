// Records a ~2 minute product demo of a running Atlas stack (http://localhost:3000).
// Usage: npm i playwright@1.57.0 ffmpeg-static (anywhere), then
//   NODE_PATH=<that dir>/node_modules node scripts/demo_video.js <out-dir>
// Uploads the three notes in samples/demo-upload/, so run it against a stack that has not seen them yet.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const OUT = path.resolve(process.argv[2] || "docs/demo");
const URL = "http://localhost:3000";
const DEMO_DIR = path.resolve(__dirname, "../samples/demo-upload");
const DEMO_FILES = fs.readdirSync(DEMO_DIR).filter((f) => f.endsWith(".md")).map((f) => path.join(DEMO_DIR, f));
const W = 1280;
const H = 800;
const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

// Caption bar + visible cursor, injected into every page load (video capture has no OS cursor).
const OVERLAY = () => {
  const boot = () => {
    if (document.getElementById("demo-caption")) return;
    const cap = document.createElement("div");
    cap.id = "demo-caption";
    Object.assign(cap.style, {
      position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: 2147483647,
      maxWidth: "860px", padding: "12px 20px", borderRadius: "12px", background: "rgba(20,20,22,.88)", color: "#fff",
      font: "500 17px/1.4 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", textAlign: "center",
      boxShadow: "0 6px 24px rgba(0,0,0,.25)", transition: "opacity .35s", opacity: "0", pointerEvents: "none",
    });
    document.body.appendChild(cap);
    const cur = document.createElement("div");
    cur.id = "demo-cursor";
    Object.assign(cur.style, {
      position: "fixed", left: "0", top: "0", width: "18px", height: "18px", marginLeft: "-9px", marginTop: "-9px",
      borderRadius: "50%", background: "rgba(232,93,74,.85)", border: "2px solid #fff", zIndex: 2147483647,
      pointerEvents: "none", boxShadow: "0 1px 6px rgba(0,0,0,.35)", transition: "transform .12s",
    });
    document.body.appendChild(cur);
    document.addEventListener("mousemove", (e) => { cur.style.left = e.clientX + "px"; cur.style.top = e.clientY + "px"; }, true);
    document.addEventListener("mousedown", () => { cur.style.transform = "scale(.7)"; }, true);
    document.addEventListener("mouseup", () => { cur.style.transform = "scale(1)"; }, true);
    window.__caption = (text) => {
      cap.style.opacity = text ? "1" : "0";
      if (text) cap.textContent = text;
    };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const ctx = await browser.newContext({
    viewport: { width: W, height: H },
    colorScheme: "light",
    recordVideo: { dir: OUT, size: { width: W, height: H } },
  });
  await ctx.addInitScript(OVERLAY);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  const pause = (ms) => page.waitForTimeout(ms);
  const caption = (text) => page.evaluate((t) => window.__caption && window.__caption(t), text);
  let mouse = { x: W / 2, y: H / 2 };
  const moveTo = async (x, y) => {
    await page.mouse.move(x, y, { steps: 18 });
    mouse = { x, y };
  };
  const clickLoc = async (loc) => {
    await loc.scrollIntoViewIfNeeded();
    const b = await loc.boundingBox();
    if (!b) throw new Error("element not visible");
    await moveTo(b.x + b.width / 2, b.y + b.height / 2);
    await pause(250);
    await page.mouse.down();
    await page.mouse.up();
  };
  const jobs = () => page.request.get(`${URL}/api/jobs/status`).then((r) => r.json());
  const filtersOpen = async () => {
    if (!(await page.locator("aside.filters").count())) await clickLoc(page.getByRole("button", { name: "Show filters" }));
  };

  // 1. Open the app: graph loading + layout feedback.
  await page.goto(URL);
  await caption("Atlas turns a folder of Markdown notes into a map of related ideas");
  await page.waitForSelector("canvas", { timeout: 30000 });
  await page.locator('[data-testid="graph-overlay"]').waitFor({ state: "detached", timeout: 30000 }).catch(() => {});
  await moveTo(640, 420);
  await pause(3500);
  log("graph ready");

  // 2. Upload three new notes: byte progress, then server processing.
  await caption("Upload Markdown files: live progress while they upload");
  const uploadBtn = page.getByRole("button", { name: "Upload", exact: true });
  await moveTo(...Object.values(await uploadBtn.boundingBox().then((b) => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 }))));
  await pause(400);
  await page.locator('[data-testid="upload-input"]').setInputFiles(DEMO_FILES);
  log("uploading", DEMO_FILES.length);
  await pause(2500);

  // 3. Indexing: per-file stages, ETA, live graph growth.
  await caption("Indexing: each note is read, parsed, embedded, summarized by Claude and linked");
  const start = Date.now();
  let idleSince = 0;
  while (Date.now() - start < 70000) {
    const s = await jobs();
    if ((s.counts.pending ?? 0) === 0 && (s.counts.running ?? 0) === 0) {
      if (!idleSince) idleSince = Date.now();
      if (Date.now() - idleSince > 2500) break;
    } else idleSince = 0;
    await pause(700);
  }
  log("indexing done after", Math.round((Date.now() - start) / 1000), "s");
  await caption("New notes join the graph as soon as they finish");
  await pause(4000);

  // 4. Search, then open the note that used to be a ghost link.
  await caption("Search every note by keyword and meaning (Cmd+K)");
  await page.keyboard.press("Meta+K");
  const box = page.locator('input[aria-label="Search notes"]').first();
  await box.waitFor();
  await box.pressSequentially("ryokan", { delay: 110 });
  await page.waitForSelector('[role="listbox"][aria-label="Search results"] [role="option"]', { timeout: 15000 });
  await pause(1800);
  await page.keyboard.press("Enter");
  await pause(1500);
  await caption("'Kyoto Ryokan List' was a ghost link; now it is a real note with a Claude summary");
  await page.locator("aside.side-panel h2, aside.side-panel h1").first().hover().catch(() => {});
  await pause(5000);

  // 5. Why connected?
  await caption("Why connected? Matching passages from both notes, plus Claude's reason");
  await clickLoc(page.getByRole("button", { name: "Why connected?" }).first());
  await page.getByRole("dialog").waitFor();
  await pause(5500);
  await clickLoc(page.getByRole("dialog").getByRole("button", { name: "Close" }));
  await pause(600);

  // 6. Travel along related notes; breadcrumbs keep the path.
  await caption("Travel from note to note; the breadcrumb trail keeps your path");
  await clickLoc(page.locator(".related .link-btn.strong").first());
  await pause(2800);
  await clickLoc(page.locator(".related .link-btn.strong").nth(1));
  await pause(2800);
  await page.keyboard.press("Alt+ArrowLeft");
  await pause(2000);

  // 7. Local graph depth.
  await caption("Local graph: show neighbours up to three hops away");
  await filtersOpen();
  const local = page.getByRole("group", { name: "Graph scope" }).getByRole("button", { name: "Local" });
  if ((await local.getAttribute("aria-pressed")) !== "true") await clickLoc(local);
  const depth = page.locator('aside.filters input[type="range"]').first();
  await clickLoc(depth);
  await depth.fill("2");
  await pause(3500);

  // 8. Global map + filters.
  await caption("Filter the whole map: keep only strong links, or focus on one theme");
  await clickLoc(page.getByRole("group", { name: "Graph scope" }).getByRole("button", { name: "Global" }));
  await pause(2500);
  const score = page.locator('aside.filters input[type="range"]').last();
  await clickLoc(score);
  for (const v of ["0.6", "0.7", "0.8"]) {
    await score.fill(v);
    await pause(1100);
  }
  const theme = page.locator('aside.filters input[type="checkbox"]').nth(4);
  if (await theme.count()) {
    await clickLoc(theme);
    await pause(3000);
    await clickLoc(theme);
    await pause(1200);
  }

  // 9. Dark mode and close.
  await caption("Light and dark themes");
  await clickLoc(page.getByRole("button", { name: "Switch to dark theme" }));
  await pause(3000);
  await caption("Atlas: local-first, runs with one docker compose up");
  await pause(3500);
  await caption("");
  await pause(500);

  const video = page.video();
  await ctx.close();
  await browser.close();
  const raw = await video.path();
  const webm = path.join(OUT, "atlas-demo.webm");
  fs.renameSync(raw, webm);
  log("video:", webm, "page errors:", JSON.stringify(errors));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
