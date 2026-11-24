/* Opt-in check against the actual app and Harness; creates a dedicated test project.
 * Credentials and browser state stay in ignored local files and are never logged.
 * Run with --live only when a real provider call is intended.
 */
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "../../../..");
const out = path.join(root, "adlc-flow/data/local-project-live-check");
const stateFile = path.join(out, "browser-state.json");
const phase = process.argv[2] ?? "inspect";
const env = require("dotenv").parse(fs.readFileSync(path.join(root, ".env.pokedev-login")));
fs.mkdirSync(out, { recursive: true });
const source = path.join(out, "source");
function git(...args) { return execFileSync("git", ["-C", source, ...args], { encoding: "utf8", windowsHide: true }).trim(); }
function sourceFixture() {
  if (!fs.existsSync(path.join(source, ".git"))) {
    fs.mkdirSync(source, { recursive: true });
    fs.writeFileSync(path.join(source, "README.md"), "# Poke Dev local project check\n\nA small repository for live workflow verification.\n");
    git("init"); git("add", "README.md");
    git("-c", "user.name=Poke Dev Check", "-c", "user.email=check@example.invalid", "commit", "-m", "Initial live-check source");
  }
  return git("rev-parse", "HEAD");
}
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe" });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...(fs.existsSync(stateFile) ? { storageState: stateFile } : {}) });
  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  try {
    await page.goto("http://localhost:3000/projects", { waitUntil: "domcontentloaded" });
    await Promise.race([
      page.locator("#login-username").waitFor(),
      page.getByRole("heading", { name: "Local projects", exact: true }).waitFor(),
    ]);
    if (await page.locator("#login-username").isVisible()) {
      await page.locator("#login-username").fill(env.POKE_DEV_USERNAME);
      await page.locator("#form-login-password").fill(env.POKE_DEV_PASSWORD);
      await page.getByRole("button", { name: /sign in/i }).click();
      await page.waitForURL(url => !url.pathname.includes("login"));
      await page.goto("http://localhost:3000/projects", { waitUntil: "domcontentloaded" });
    }
    await page.getByRole("heading", { name: "Local projects", exact: true }).waitFor();
    await context.storageState({ path: stateFile });
    if (phase === "inspect") {
      console.log((await page.locator("body").innerText()).slice(0,3500));
    } else if (phase === "open") {
      const commit = sourceFixture();
      await page.getByRole("button", { name: "Open local folder", exact: true }).click();
      await page.getByLabel("Folder location").fill(source);
      await page.getByRole("button", { name: "Go", exact: true }).click();
      await page.getByRole("button", { name: /^use this folder$/i }).click();
      await page.waitForURL(/\/all\/folder\//);
      assert.equal(git("status", "--porcelain"), "");
      fs.writeFileSync(path.join(out,"flow-check.json"), JSON.stringify({ projectId: page.url().split("/").at(-1), source, commit },null,2));
      console.log("Local folder selected", page.url());
      console.log((await page.locator("body").innerText()).slice(0,3000));
    } else if (phase === "flow") {
      const resultFile=path.join(out,"flow-check.json");
      const result=JSON.parse(fs.readFileSync(resultFile,"utf8"));
      await page.goto(`http://localhost:3000/all/folder/${result.projectId}`,{waitUntil:"domcontentloaded"});
      await page.getByRole("button",{name:/^new workflow$/i}).first().click();
      await page.getByTestId("adlc-workspace-designer").waitFor();
      result.flowId=page.url().match(/\/flow\/([^/]+)/)[1];
      fs.writeFileSync(resultFile,JSON.stringify(result,null,2));
      await page.getByRole("button",{name:/^use coding starter$/i}).click();
      await page.getByLabel("Goal",{exact:true}).fill("Verify the selected local project with a small README change.");
      await page.getByLabel("Requirement",{exact:true}).fill('Append exactly the line "Live project selection verified." to README.md. Preserve every existing line. Change only README.md in the isolated session working copy. Do not commit, push, deploy, install dependencies, or use a remote sandbox. Report the change for human review.');
      await page.getByRole("button",{name:/^save stage$/i}).click();
      await page.getByRole("button",{name:/^review plan$/i}).click();
      await page.getByRole("heading",{name:"ADLC Plan Preview"}).waitFor();
      console.log("Live workflow:",page.url());
      console.log((await page.getByRole("dialog").innerText()).slice(0,5000));
    } else if (phase === "run") {
      assert.ok(process.argv.includes("--live"),"A real agent call requires --live");
      const resultFile=path.join(out,"flow-check.json");
      const result=JSON.parse(fs.readFileSync(resultFile,"utf8"));
      await page.goto(`http://localhost:3000/flow/${result.flowId}/folder/${result.projectId}`,{waitUntil:"domcontentloaded"});
      await page.getByTestId("adlc-workspace-designer").waitFor();
      await page.getByRole("button",{name:/^review plan$/i}).click();
      await page.getByRole("button",{name:/^accept plan$/i}).click();
      await page.getByRole("button",{name:"Run This Plan",exact:true}).click();
      await page.waitForURL(/\/runs\/[a-f0-9-]+/);
      result.runId=page.url().match(/\/runs\/([^/]+)/)[1];
      fs.writeFileSync(resultFile,JSON.stringify(result,null,2));
      console.log("Real agent run:",page.url());
      console.log((await page.locator("body").innerText()).slice(0,4000));
    } else if (phase === "review" || phase === "finish") {
      const result=JSON.parse(fs.readFileSync(path.join(out,"flow-check.json"),"utf8"));
      await page.goto(`http://localhost:3000/runs/${result.runId}`,{waitUntil:"domcontentloaded"});
      await page.getByRole("heading",{level:1}).waitFor();
      if (phase === "finish") {
        const submit=page.getByRole("button",{name:/^submit failed result$/i});
        if (await submit.count()) await submit.click();
        let run;
        for (let i=0;i<12;i++) {
          const response=await context.request.get(`http://localhost:3000/api/v1/adlc/runs/${result.runId}`);
          run=await response.json();
          if (["FAILED","PAUSED","SUCCEEDED","CANCELLED"].includes(run.status)) break;
          await page.waitForTimeout(1000);
        }
        assert.ok(["FAILED","PAUSED"].includes(run.status),"A submitted provider failure must stop the workflow under its failure policy");
        assert.equal(run.tasks[0].status,"FAILED");
        assert.equal(git("rev-parse","HEAD"),result.commit);
        assert.equal(git("status","--porcelain"),"");
        console.log("Live provider failure submitted to workflow; source stayed unchanged.");
        await page.reload({waitUntil:"domcontentloaded"});
        await page.getByRole("heading",{level:1}).waitFor();
      }
      console.log((await page.locator("body").innerText()).slice(0,6000));
    }
    await page.screenshot({ path: path.join(out,`${phase}.png`), fullPage: true });
    if (errors.length) console.log("App errors:", JSON.stringify(errors));
  } catch (e) {
    console.log("Check failed:", e.message.split("\n")[0]);
    await page.screenshot({ path: path.join(out,`${phase}-failure.png`), fullPage: true }).catch(()=>{});
    console.log("Current page:", page.url());
    if (!page.isClosed()) console.log((await page.locator("body").innerText({timeout:2000})).slice(0,4500));
    throw e;
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.message); process.exitCode=1;});
