export const SCRATCH_PREFIX = "/scratch";
export const TMP_PREFIX = "/tmp";

export function isScratchPath(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  return (
    normalized.startsWith(SCRATCH_PREFIX + "/") ||
    normalized === SCRATCH_PREFIX ||
    normalized.startsWith(TMP_PREFIX + "/") ||
    normalized === TMP_PREFIX
  );
}

export function shouldIgnoreVfsPath(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  if (isScratchPath(normalized)) return true;

  const parts = normalized.split("/").filter(Boolean);
  return parts.some((part) =>
    part === "node_modules" ||
    part === ".git" ||
    part === "__pycache__" ||
    part === ".pytest_cache" ||
    part === ".venv" ||
    part === "venv" ||
    part === ".cache" ||
    part === "dist" ||
    part === "build" ||
    part === ".DS_Store"
  );
}

export function normalizeVfsPath(filePath: string): string {
  return (
    "/" +
    filePath
      .replace(/\\/g, "/")
      .replace(/^\/+/, "")
      .split("/")
      .filter((part) => part && part !== "." && part !== "..")
      .join("/")
  );
}
