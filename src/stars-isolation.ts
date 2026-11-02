import { lstatSync, mkdirSync, realpathSync, readdirSync, copyFileSync } from "fs";
import { dirname, join, resolve } from "path";
import { spawnSync } from "child_process";

export function validateTestConfig(config: Record<string, string>, productionToken: string | undefined, otherProductionToken?: string): {token: string; admin: number; invoices: boolean; refunds: boolean} {
  const token = (config.TEST_BOT_TOKEN || "").trim(), prod = (productionToken || "").trim();
  const format = /^[1-9]\d{5,14}:[A-Za-z0-9_-]{30,}$/;
  if (config.TEST_ENVIRONMENT !== "telegram-test" || !format.test(token) || !format.test(prod) || token.split(":")[0] === prod.split(":")[0] || (otherProductionToken && token.split(":")[0] === otherProductionToken.trim().split(":")[0])) throw new Error("test bot identity or environment invalid");
  const admin = Number(config.TEST_ADMIN_ID);
  if (!/^[1-9]\d*$/.test(config.TEST_ADMIN_ID || "") || !Number.isSafeInteger(admin) || admin > 2**52) throw new Error("test administrator invalid");
  if (!["0", "1"].includes(config.TEST_INVOICES || "") || !["0", "1"].includes(config.TEST_REFUNDS || "")) throw new Error("test switches invalid");
  return {token, admin, invoices: config.TEST_INVOICES === "1", refunds: config.TEST_REFUNDS === "1"};
}

function checked(path: string, directory: boolean): void {
  const info = lstatSync(path);
  if (info.isSymbolicLink() || (directory ? !info.isDirectory() : !info.isFile()) || (!directory && info.nlink !== 1)) throw new Error("unsafe test path");
}
function present(path: string): boolean {
  try { lstatSync(path); return true; } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}

export function validateSettingsFile(project: string, sandbox: string): string {
  const file = join(sandbox, "settings.env");
  checked(file,false);
  if (process.platform === "win32") {
    const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-File", join(project,"storage","journal_acl.ps1"), "-Action", "check-file", "-Target", file], {stdio:"ignore", windowsHide:true});
    if (result.error || result.status !== 0) throw new Error("unsafe test settings ACL");
  } else if ((lstatSync(file).mode & 0o077) !== 0 || (typeof process.getuid === "function" && lstatSync(file).uid !== process.getuid())) throw new Error("unsafe test settings permissions");
  return file;
}

export function prepareSandbox(project: string): string {
  const base = realpathSync(project), target = join(base, ".stars-test");
  if (dirname(target) !== base || resolve(target) === resolve(base)) throw new Error("unsafe test root");
  if (present(target)) checked(target,true);
  if (process.platform === "win32") {
    const script = join(base, "storage", "journal_acl.ps1");
    const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-File", script, "-Action", "ensure", "-Target", target], {stdio:"ignore", windowsHide:true});
    if (result.error || result.status !== 0) throw new Error("unsafe test root ACL");
  } else if (!present(target)) mkdirSync(target, {mode:0o700});
  checked(target, true);
  if (realpathSync(target) !== target) throw new Error("unsafe test root alias");
  if (process.platform !== "win32") {
    const info = lstatSync(target);
    if ((info.mode & 0o077) || (typeof process.getuid === "function" && info.uid !== process.getuid())) throw new Error("unsafe test root permissions");
  }
  for (const name of ["users.sqlite3", "users.sqlite3-wal", "users.sqlite3-shm", "users.sqlite3-journal"]) {
    const p = join(target,name); if (present(p)) checked(p,false);
  }
  for (const name of ["app", "storage"]) {
    const dir = join(target,name); if (!present(dir)) mkdirSync(dir, {mode:0o700}); checked(dir,true);
    const source = join(base,name);
    const files = name === "app" ? readdirSync(source).filter(x => /^[a-z_]+\.py$/.test(x)) : ["service.py"];
    for (const file of files) {
      const from = join(source,file), to = join(dir,file);
      checked(from,false); if (present(to)) checked(to,false);
      copyFileSync(from,to);
    }
  }
  const journal = join(target,"payment-journal"); if (present(journal)) checked(journal,true);
  return target;
}
