import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

export async function writeJson(filePath: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporary, filePath);
}

export async function readJsonIfExists<T>(filePath: string): Promise<T | undefined> {
  return await readFile(filePath, "utf8")
    .then((text) => JSON.parse(text) as T)
    .catch((error: unknown) => {
      const code = error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code)
        : "";
      if (code === "ENOENT") return undefined;
      throw error;
    });
}
