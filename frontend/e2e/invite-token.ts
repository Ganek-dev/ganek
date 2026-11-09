import { createHash, createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

/** The stack's GANEK_SECRET_KEY: E2E_SECRET_KEY if set, else the repo-root
 * .env that `docker compose` handed the backend (CI copies .env.example). */
export function stackSecretKey(): string {
  const fromEnv = process.env.E2E_SECRET_KEY;
  if (fromEnv) return fromEnv;
  const envFile = path.resolve(__dirname, "..", "..", ".env");
  const text = fs.readFileSync(envFile, "utf8");
  for (const raw of text.split("\n")) {
    const match = /^\s*GANEK_SECRET_KEY\s*=\s*(.*)$/.exec(raw);
    if (!match) continue;
    let value = match[1].replace(/\s+#.*$/, "").trim();
    if (/^(["']).*\1$/.test(value)) value = value.slice(1, -1);
    return value;
  }
  throw new Error(`GANEK_SECRET_KEY not found in ${envFile}; set E2E_SECRET_KEY`);
}

function b64url(buf: Buffer): string {
  return buf.toString("base64url").replace(/=+$/, "");
}

/** Team invite links are never returned by the API (they only travel by
 * email), so the suite signs one the way the backend does:
 * itsdangerous URLSafeTimedSerializer(secret, salt="ganek-team-invite")
 * over the invite id (app/core/security.py create_invite_token) - HMAC-SHA1,
 * "django-concat" key derivation, uncompressed JSON payload. */
export function signInviteToken(inviteId: string, secretKey: string, now = Date.now()): string {
  const salt = "ganek-team-invite";
  const payload = b64url(Buffer.from(JSON.stringify(inviteId), "utf8"));
  let seconds = Math.floor(now / 1000);
  const bytes: number[] = [];
  while (seconds > 0) {
    bytes.unshift(seconds & 0xff);
    seconds = Math.floor(seconds / 256);
  }
  const value = `${payload}.${b64url(Buffer.from(bytes))}`;
  const key = createHash("sha1")
    .update(salt + "signer" + secretKey)
    .digest();
  const signature = b64url(createHmac("sha1", key).update(value).digest());
  return `${value}.${signature}`;
}
