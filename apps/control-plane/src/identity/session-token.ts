import { createHash, randomBytes } from "node:crypto";

const TOKEN_BYTES = 32;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export interface SessionToken {
  token: string;
  tokenHash: string;
}

export function hashSessionToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export function isValidSessionToken(token: string): boolean {
  return TOKEN_PATTERN.test(token);
}

export function createSessionToken(): SessionToken {
  const token = randomBytes(TOKEN_BYTES).toString("base64url");
  return { token, tokenHash: hashSessionToken(token) };
}
