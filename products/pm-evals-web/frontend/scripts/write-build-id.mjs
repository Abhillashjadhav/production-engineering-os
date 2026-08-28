import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const distRoot = path.join(frontendRoot, "dist");

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await filesUnder(absolute)));
    } else if (entry.isFile() && entry.name !== "BUILD_ID") {
      files.push(absolute);
    }
  }
  return files;
}

const digest = createHash("sha256");
for (const absolute of await filesUnder(distRoot)) {
  const relative = path.relative(distRoot, absolute).split(path.sep).join("/");
  digest.update(relative);
  digest.update("\0");
  digest.update(await readFile(absolute));
  digest.update("\0");
}

await writeFile(path.join(distRoot, "BUILD_ID"), `sha256:${digest.digest("hex")}\n`);
