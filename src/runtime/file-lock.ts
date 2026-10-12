import { open, readFile, rm } from "node:fs/promises";

interface LockHolder {
  pid?: number;
  createdAt?: string;
}

/**
 * Prevent two live experiment processes from mutating the same manifest.
 * A lock left behind by a terminated process is removed after its PID is
 * confirmed absent.
 */
export async function acquireProcessFileLock(
  targetPath: string,
  purpose: string,
): Promise<() => Promise<void>> {
  const lockPath = `${targetPath}.lock`;
  const tryAcquire = async (removedStale: boolean): Promise<() => Promise<void>> => {
    try {
      const handle = await open(lockPath, "wx");
      await handle.writeFile(`${JSON.stringify({
        pid: process.pid,
        createdAt: new Date().toISOString(),
        targetPath,
        purpose,
      }, null, 2)}\n`, "utf8");
      return async () => {
        await handle.close();
        await rm(lockPath, { force: true });
      };
    } catch (error) {
      const code = error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code)
        : "";
      if (code !== "EEXIST") throw error;
      const holder: LockHolder = await readFile(lockPath, "utf8")
        .then((text) => JSON.parse(text) as LockHolder)
        .catch((): LockHolder => ({}));
      let alive = typeof holder.pid === "number";
      if (alive) {
        try {
          process.kill(holder.pid!, 0);
        } catch (probeError) {
          const probeCode = probeError && typeof probeError === "object" && "code" in probeError
            ? String((probeError as { code?: unknown }).code)
            : "";
          if (probeCode === "ESRCH") alive = false;
        }
      }
      if (!alive && !removedStale) {
        await rm(lockPath, { force: true });
        return await tryAcquire(true);
      }
      throw new Error(
        `${purpose} is already controlled by an active process `
        + `(pid=${holder.pid ?? "unknown"}, createdAt=${holder.createdAt ?? "unknown"}): ${targetPath}`,
      );
    }
  };
  return await tryAcquire(false);
}
