/*
 * Artifact build recipe for `y module publish` (lifted from spike-2412/build.mjs).
 *
 *   1. esbuild  : index.tsx -> ESM bundle, externals redirected to alias shims
 *   2. tailwind : generated CSS entry -> utilities-only stylesheet
 *                 (theme(reference) + source(none) + no preflight — F1/F2)
 *   3. scope    : wrap stylesheet so it cannot restyle host chrome (@scope)
 *   4. inline   : append `export const css = "…"` (decision D2)
 *   5. hash     : sha256 of the final bytes -> manifest.json
 *
 * Run (from the materialized SDK dir on the VM):
 *   node build.mjs --slug <slug> --src <module-ui-dir> --out <out-dir> [--scope=scope|prefix|none]
 */
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback = undefined) {
  const flag = process.argv.find((a) => a.startsWith(`${name}=`));
  if (flag) return flag.slice(name.length + 1);
  const idx = process.argv.indexOf(name);
  if (idx >= 0 && process.argv[idx + 1] && !process.argv[idx + 1].startsWith("-")) {
    return process.argv[idx + 1];
  }
  return fallback;
}

const slug = arg("--slug");
const srcDir = path.resolve(arg("--src", path.join(here, "..")));
const outDir = path.resolve(arg("--out", path.join(srcDir, ".build", slug || "out")));
const scopeMode = arg("--scope", "scope");
const contractPath = path.join(here, "contract.json");

if (!slug) {
  console.error("usage: node build.mjs --slug <slug> [--src <ui-dir>] [--out <out-dir>] [--scope=scope|prefix|none]");
  process.exit(2);
}

const tsxPath = path.join(srcDir, "index.tsx");
if (!fs.existsSync(tsxPath)) {
  console.error(`source not found: ${tsxPath}`);
  process.exit(1);
}

const contract = JSON.parse(fs.readFileSync(contractPath, "utf8"));
const minHostVersion = Number(contract.version) || 1;

// @y/design is inlined at build time (todo 3657). It is not a runtime
// external. Resolve from the SDK node_modules so the importer can live
// under y-module and still hit the locked package. Root entry only.
function resolveDesignPackage() {
  const pkgJsonPath = path.join(here, "node_modules", "@y", "design", "package.json");
  if (!fs.existsSync(pkgJsonPath)) {
    throw new Error(
      `@y/design is not installed in ${path.join(here, "node_modules")}; run npm install in the SDK dir`,
    );
  }
  const pkg = JSON.parse(fs.readFileSync(pkgJsonPath, "utf8"));
  const entryRel = pkg.exports?.["."]?.import || pkg.module || pkg.main;
  if (!entryRel || typeof entryRel !== "string") {
    throw new Error(`@y/design package.json has no ESM entry: ${pkgJsonPath}`);
  }
  const entry = path.resolve(path.dirname(pkgJsonPath), entryRel);
  if (!fs.existsSync(entry)) {
    throw new Error(`@y/design entry not found: ${entry}`);
  }
  const distDir = path.dirname(entry);
  const distFiles = fs
    .readdirSync(distDir)
    .filter((name) => name.endsWith(".js"))
    .map((name) => path.join(distDir, name))
    .sort();
  return {
    version: String(pkg.version || ""),
    pkgJsonPath,
    entry,
    distFiles,
  };
}

const designPkg = resolveDesignPackage();

fs.mkdirSync(outDir, { recursive: true });

// Stage dist JS under .cache so esbuild's path comment does not contain the
// bare specifier `@y/design`. The alias points at this copy. node_modules
// stays the digest input. .cache is not part of the SDK content digest.
const cacheDir = path.join(here, ".cache");
fs.mkdirSync(cacheDir, { recursive: true });
const designStage = path.join(cacheDir, "y-design");
fs.rmSync(designStage, { recursive: true, force: true });
fs.mkdirSync(designStage, { recursive: true });
for (const file of designPkg.distFiles) {
  fs.copyFileSync(file, path.join(designStage, path.basename(file)));
}
const designEntry = path.join(designStage, path.basename(designPkg.entry));

// ---------------------------------------------------------------- 1. esbuild
const shim = (f) => path.join(here, "shims", f);
let result;
try {
  result = await build({
    entryPoints: [tsxPath],
    bundle: true,
    format: "esm",
    target: "es2022",
    jsx: "automatic",
    platform: "browser",
    write: false,
    logLevel: "silent",
    // Pin the working directory so path comments in the bundle (and thus the
    // content hash) do not depend on the caller's cwd. The Python CLI also
    // runs this script with cwd=sdk dir; absWorkingDir is belt-and-suspenders.
    absWorkingDir: here,
    alias: {
      "@y/design": designEntry,
      react: shim("react.cjs"),
      "react-dom": shim("react-dom.cjs"),
      "react-dom/client": shim("react-dom-client.cjs"),
      "react/jsx-runtime": shim("react-jsx-runtime.cjs"),
      swr: shim("swr.cjs"),
      "swr/infinite": shim("swr-infinite.cjs"),
      recharts: shim("recharts.cjs"),
      "lightweight-charts": shim("lightweight-charts.cjs"),
      "react-markdown": shim("react-markdown.cjs"),
      "remark-gfm": shim("remark-gfm.cjs"),
      "@y/host": shim("y-host.cjs"),
    },
  });
} catch (err) {
  // esbuild puts a readable multi-line message on err.errors / err.message.
  const msg = err.errors
    ? err.errors.map((e) => `${e.location?.file || ""}:${e.location?.line || ""}: ${e.text}`).join("\n")
    : err.message || String(err);
  console.error(msg);
  process.exit(1);
}
const js = result.outputFiles[0].text;

// The load-bearing invariant: a blob: module cannot resolve bare specifiers.
const leftoverImports = [...js.matchAll(/^\s*(?:import|export)[^;]*?from\s*["']([^"']+)["']/gm)].map(
  (m) => m[1],
);
if (leftoverImports.length) {
  throw new Error(`bundle still imports external specifiers: ${leftoverImports.join(", ")}`);
}

// --------------------------------------------------------------- 2. tailwind
// Authors write ui/index.tsx and sibling files; the CSS entry is generated so
// the three D3 requirements (theme(reference), source(none), no preflight) cannot be forgotten.
// theme(reference) on the default theme import is MANDATORY (F1) or spacing /
// radius / text utilities silently vanish. source(none) is MANDATORY (F2) or
// Tailwind scans the whole VM home directory.
//
// The entry file must live under the SDK dir so `tailwindcss/theme.css` resolves
// via this package's node_modules (resolution walks from the CSS file, not --cwd).
const cssEntry = path.join(cacheDir, `${slug}.entry.css`);
const tsxRel = path.relative(cacheDir, tsxPath).split(path.sep).join("/");
const partsDir = srcDir;
const partsRel = path.relative(cacheDir, partsDir).split(path.sep).join("/");
// Sibling of <slug>/ is code/y-module/shared/ui: leaf UI imported across
// modules. Distinct from the `common` module, which vendors Python/tables.
const sharedUiDir = path.join(path.dirname(path.dirname(srcDir)), "shared", "ui");
const sourceLines = [
  "/* generated by y module publish — do not edit */",
  '@import "tailwindcss/theme.css" theme(reference);',
  '@import "tailwindcss/utilities.css" layer(utilities) source(none);',
  '@import "../theme.css";',
  `@source "${tsxRel.startsWith(".") ? tsxRel : `./${tsxRel}`}";`,
  // The full UI tree covers sibling parts below the canonical index entry.
  `@source "${partsRel.startsWith(".") ? partsRel : `./${partsRel}`}/**/*.{tsx,ts}";`,
];
if (fs.existsSync(sharedUiDir)) {
  const sharedRel = path.relative(cacheDir, sharedUiDir).split(path.sep).join("/");
  sourceLines.push(
    `@source "${sharedRel.startsWith(".") ? sharedRel : `./${sharedRel}`}/**/*.{tsx,ts}";`,
  );
}
// Explicit source of the staged @y/design dist JS. Only when this module
// or shared/ui imports the package, so other modules do not gain its
// utilities. The list is the staged copies of designPkg.distFiles, the same
// bytes source_digest hashes. Do not scan node_modules or leftover stage files.
const designExtraDirs = fs.existsSync(sharedUiDir) ? [sharedUiDir] : [];
const usesDesign = sourceImportsDesign(tsxPath, partsDir, designExtraDirs);
if (usesDesign) {
  for (const file of designPkg.distFiles) {
    const staged = path.join(designStage, path.basename(file));
    const distRel = path.relative(cacheDir, staged).split(path.sep).join("/");
    sourceLines.push(`@source "${distRel.startsWith(".") ? distRel : `./${distRel}`}";`);
  }
}
sourceLines.push("");
fs.writeFileSync(cssEntry, sourceLines.join("\n"));

const tailwindBin = path.join(here, "node_modules", ".bin", "tailwindcss");
if (!fs.existsSync(tailwindBin)) {
  console.error(`tailwindcss CLI not found at ${tailwindBin}; run: (cd ${here} && npm install)`);
  process.exit(1);
}

let cssRaw;
try {
  cssRaw = execFileSync(tailwindBin, ["-i", cssEntry, "--cwd", here], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
} catch (err) {
  const stderr = err.stderr?.toString?.() || err.message || String(err);
  console.error(stderr);
  process.exit(1);
}

// ------------------------------------------------------------------ 3. scope
// `@property` is only valid at the top level — nesting it inside `@scope` gets
// the whole rule dropped, which silently breaks every `ring-*` / `shadow-*`
// utility (F3). Hoist those out before wrapping.
function hoistAtProperty(css) {
  const hoisted = [];
  const rest = css.replace(/@property\s+[^{]+\{[^}]*\}\s*/g, (m) => {
    hoisted.push(m.trim());
    return "";
  });
  return { hoisted: hoisted.join("\n"), rest };
}

function scopeCss(cssIn, artifactSlug, mode) {
  if (mode === "none") return cssIn;
  const { hoisted, rest: css } = hoistAtProperty(cssIn);
  if (mode === "scope") {
    // `@scope` adds no specificity, so artifact utilities stay peers of the
    // host's identical utilities instead of quietly outranking them.
    return `${hoisted}\n@scope ([data-y-artifact="${artifactSlug}"]) {\n${css}\n}\n`;
  }
  return `${hoisted}\n${prefixSelectors(css, artifactSlug)}\n`;
}

// `prefix` fallback: mechanical descendant-prefix on every top-level style rule.
// A regex cannot do this correctly — skip at-rule preludes, leave nested rules
// alone, ignore comments (brace walker from the spike).
function prefixSelectors(css, artifactSlug) {
  const out = [];
  let prelude = "";
  const stack = [];
  for (let i = 0; i < css.length; i++) {
    const ch = css[i];
    if (ch === "/" && css[i + 1] === "*") {
      const end = css.indexOf("*/", i + 2);
      out.push(css.slice(i, end + 2));
      i = end + 1;
      continue;
    }
    if (ch === "{") {
      const trimmed = prelude.trim();
      const isAtRule = trimmed.startsWith("@");
      const insideStyleRule = stack.some(Boolean);
      if (!isAtRule && !insideStyleRule) {
        const scoped = trimmed
          .split(",")
          .map((s) => `[data-y-artifact="${artifactSlug}"] ${s.trim()}`)
          .join(", ");
        out.push(prelude.slice(0, prelude.length - prelude.trimStart().length), scoped, " {");
      } else {
        out.push(prelude, "{");
      }
      stack.push(!isAtRule);
      prelude = "";
      continue;
    }
    if (ch === "}") {
      out.push(prelude, "}");
      stack.pop();
      prelude = "";
      continue;
    }
    if (ch === ";" && stack.length === 0) {
      out.push(prelude, ";");
      prelude = "";
      continue;
    }
    prelude += ch;
  }
  return out.join("") + prelude;
}

const css = scopeCss(cssRaw, slug, scopeMode);

// ----------------------------------------------------------------- 4. inline
const bundle = `${js}\nexport const css = ${JSON.stringify(css)};\nexport const slug = ${JSON.stringify(slug)};\nexport const minHostVersion = ${minHostVersion};\n`;

// ------------------------------------------------------------------- 5. hash
// source_digest covers the whole UI tree, so editing any sibling file changes
// this field. The bundle sha256 stays the integrity control, while source_digest
// reflects whether any source input changed.
function sourceImportsDesign(entryPath, partsDirPath, extraDirs = []) {
  const spec = /(?:from\s+|import\s*\(?)\s*["']@y\/design["']/;
  const files = [entryPath, ...collectPartFiles(partsDirPath)];
  for (const extra of extraDirs) files.push(...collectPartFiles(extra));
  return files.some((file) => spec.test(fs.readFileSync(file, "utf8")));
}

function collectPartFiles(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...collectPartFiles(full));
    else if (/\.(tsx|ts)$/.test(entry.name)) out.push(full);
  }
  return out.sort();
}

function computeSourceDigest(entryPath, partsDirPath, extraDirs = [], design = null) {
  const hash = createHash("sha256");
  hash.update(fs.readFileSync(entryPath));
  const files = collectPartFiles(partsDirPath);
  for (const extra of extraDirs) {
    files.push(...collectPartFiles(extra));
  }
  for (const file of files.sort()) {
    // Basename prefix only when the design package is part of the digest.
    // Modules that do not import it keep the historical raw-bytes digest.
    if (design) {
      hash.update(path.basename(file));
      hash.update("\0");
    }
    hash.update(fs.readFileSync(file));
    if (design) hash.update("\0");
  }
  // Package identity + dist JS only. Paths are basenames so the digest does
  // not embed the machine's SDK directory.
  if (design) {
    hash.update("@y/design");
    hash.update("\0");
    hash.update(String(design.version));
    hash.update("\0");
    hash.update(fs.readFileSync(design.pkgJsonPath));
    hash.update("\0");
    for (const file of design.distFiles) {
      hash.update(path.basename(file));
      hash.update("\0");
      hash.update(fs.readFileSync(file));
      hash.update("\0");
    }
  }
  return hash.digest("hex");
}

const bytes = Buffer.from(bundle, "utf8");
const sha256 = createHash("sha256").update(bytes).digest("hex");
const sourceDigest = computeSourceDigest(
  tsxPath,
  partsDir,
  designExtraDirs,
  usesDesign ? designPkg : null,
);

const bundlePath = path.join(outDir, `${slug}.js`);
const manifestPath = path.join(outDir, "manifest.json");
fs.writeFileSync(bundlePath, bytes);
fs.writeFileSync(
  manifestPath,
  JSON.stringify(
    {
      slug,
      sha256,
      source_digest: sourceDigest,
      min_host_version: minHostVersion,
      scope_mode: scopeMode,
      bytes: bytes.length,
      css_bytes: css.length,
      bundle: bundlePath,
    },
    null,
    2,
  ),
);

// Machine-readable one-liner for the Python CLI to parse.
process.stdout.write(
  JSON.stringify({
    slug,
    sha256,
    source_digest: sourceDigest,
    min_host_version: minHostVersion,
    bytes: bytes.length,
    bundle: bundlePath,
    manifest: manifestPath,
  }) + "\n",
);
