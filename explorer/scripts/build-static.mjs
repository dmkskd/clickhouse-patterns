#!/usr/bin/env node
/** Package the checked-in Pattern Explorer UI with a compiled catalog. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const explorerDir = path.resolve(scriptDir, "..");

function options(argv) {
  const result = { single: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--single") result.single = true;
    else if (["--catalog", "--output", "--output-dir"].includes(arg)) {
      const value = argv[index + 1];
      if (!value) throw new Error(`${arg} requires a value`);
      result[arg.slice(2)] = value;
      index += 1;
    } else throw new Error(`unknown argument: ${arg}`);
  }
  if (!result.catalog) throw new Error("--catalog is required");
  return result;
}

function source(name) {
  return fs.readFileSync(path.join(explorerDir, name), "utf8");
}

function replaceOnce(value, needle, replacement) {
  if (!value.includes(needle)) throw new Error(`browser shell is missing ${needle}`);
  return value.replace(needle, replacement);
}

const args = options(process.argv.slice(2));
const catalog = fs.readFileSync(path.resolve(args.catalog), "utf8");
const css = source("app.css");
const shell = source("index.html");
// The page's local scripts, in load order, are the list of browser sources.
// catalog.js is generated and comes from --catalog; external (CDN) scripts
// stay in the page as they are.
const scripts = [...shell.matchAll(/<script src="([^":]+\.js)"><\/script>/g)]
  .map((match) => match[1])
  .filter((name) => name !== "catalog.js");

if (args.single) {
  const output = path.resolve(args.output || ".runtime/pattern-explorer.html");
  let html = replaceOnce(
    shell,
    '<link rel="stylesheet" href="app.css">',
    `<style>\n${css}\n</style>`,
  );
  const inlineScript = (value) => `<script>\n${value.replaceAll("</script", "<\\/script")}\n</script>`;
  html = replaceOnce(html, '<script src="catalog.js"></script>', inlineScript(catalog));
  for (const name of scripts) {
    html = replaceOnce(html, `<script src="${name}"></script>`, inlineScript(source(name)));
  }
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, html);
  console.log(`SINGLE-FILE CATALOG\n  HTML  ${output}\n  SIZE  ${(fs.statSync(output).size / 1024).toFixed(1)} KiB\n  mode  self-contained; works directly from file://`);
} else {
  const outputDir = path.resolve(args["output-dir"] || ".runtime/site");
  fs.mkdirSync(outputDir, { recursive: true });
  fs.copyFileSync(path.join(explorerDir, "app.css"), path.join(outputDir, "app.css"));
  for (const name of scripts) {
    fs.copyFileSync(path.join(explorerDir, name), path.join(outputDir, name));
  }
  const catalogOutput = path.join(outputDir, "catalog.js");
  if (path.resolve(args.catalog) !== catalogOutput) fs.writeFileSync(catalogOutput, catalog);
  fs.writeFileSync(path.join(outputDir, "index.html"), shell);
  console.log(`STATIC CATALOG\n  DIR   ${outputDir}\n  mode  static hosting; no backend required`);
}
