"use strict";

const {spawnSync} = require("node:child_process");
const path = require("node:path");

const python = path.join(__dirname, "..", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const result = spawnSync(python, process.argv.slice(2), {stdio: "inherit"});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
