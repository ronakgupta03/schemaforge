#!/usr/bin/env node
import { existsSync, mkdirSync, cpSync, rmSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PKG_ROOT = join(__dirname, "..");
const REPO_ROOT = join(PKG_ROOT, "..", "..");

const filterIgnored = (src) => {
  const base = src.replace(/\\/g, "/");
  return (
    !base.includes("/__pycache__") &&
    !base.includes("/.pytest_cache") &&
    !base.includes("/node_modules") &&
    !base.includes("/.vevn") &&
    !base.includes("/.venv") &&
    !base.endsWith(".pyc") &&
    !base.endsWith(".pyo") &&
    !base.includes(".egg-info")
  );
};

console.log("[prepack] staging runtime directories into packages/cli...");

// 1. Ensure UI build exists and copy to ui-dist
const repoUiDist = join(REPO_ROOT, "ui", "dist");
if (!existsSync(repoUiDist)) {
  console.log("[prepack] building ui...");
  try {
    execSync("npm run build", { cwd: join(REPO_ROOT, "ui"), stdio: "inherit" });
  } catch (err) {
    console.error("[prepack] failed to build ui:", err.message);
    process.exit(1);
  }
}

if (!existsSync(repoUiDist)) {
  console.error(`[prepack] ui build missing at ${repoUiDist}`);
  process.exit(1);
}

const pkgUiDist = join(PKG_ROOT, "ui-dist");
rmSync(pkgUiDist, { recursive: true, force: true });
cpSync(repoUiDist, pkgUiDist, { recursive: true });

// 2. Copy core, mcp-servers, agent, skills
const dirsToCopy = ["core", "mcp-servers", "agent", "skills"];
for (const dir of dirsToCopy) {
  const src = join(REPO_ROOT, dir);
  const dest = join(PKG_ROOT, dir);
  if (existsSync(src)) {
    rmSync(dest, { recursive: true, force: true });
    cpSync(src, dest, { recursive: true, filter: filterIgnored });
  }
}

// 3. Copy scripts (preserving prepack.mjs)
const srcScripts = join(REPO_ROOT, "scripts");
const destScripts = join(PKG_ROOT, "scripts");
if (existsSync(srcScripts)) {
  mkdirSync(destScripts, { recursive: true });
  const entries = readdirSync(srcScripts);
  for (const entry of entries) {
    const srcPath = join(srcScripts, entry);
    const destPath = join(destScripts, entry);
    cpSync(srcPath, destPath, { recursive: true, filter: filterIgnored });
  }
}

console.log("[prepack] successfully bundled runtime artifacts.");
