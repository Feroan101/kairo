import { describe, expect, it } from "vitest";
import { loadServerConfig } from "../src/config.ts";
import {
  hashPassword,
  verifyPassword,
  verifyUnusablePassword,
} from "../src/identity/credentials.ts";
import { hasRequiredRole } from "../src/identity/roles.ts";
import {
  createSessionToken,
  hashSessionToken,
  isValidSessionToken,
} from "../src/identity/session-token.ts";

describe("password credentials", () => {
  it("hashes and verifies a password without storing plaintext", async () => {
    const password = "correct horse battery staple";
    const hash = await hashPassword(password);

    expect(hash).toMatch(/^scrypt\$16384\$8\$1\$/);
    expect(hash).not.toContain(password);
    expect(await verifyPassword(password, hash)).toBe(true);
    expect(await verifyPassword("wrong password", hash)).toBe(false);
  });

  it("rejects missing or malformed hashes", async () => {
    expect(await verifyPassword("password", null)).toBe(false);
    expect(await verifyPassword("password", "plaintext-secret")).toBe(false);
    expect(await verifyPassword("password", "scrypt$1$1$1$c2FsdA$aGFzaA")).toBe(false);
  });

  it("keeps an unusable hash for unknown accounts", async () => {
    const hash = await hashPassword("unusable-password");
    await expect(verifyUnusablePassword("any password")).resolves.toBeUndefined();
    expect(await verifyPassword("unusable-password", hash)).toBe(true);
  });
});

describe("session tokens", () => {
  it("creates high-entropy tokens and stores only their hash", () => {
    const first = createSessionToken();
    const second = createSessionToken();

    expect(first.token).not.toBe(second.token);
    expect(isValidSessionToken(first.token)).toBe(true);
    expect(isValidSessionToken("short")).toBe(false);
    expect(first.tokenHash).toBe(hashSessionToken(first.token));
    expect(first.tokenHash).toMatch(/^[a-f0-9]{64}$/);
    expect(first.token).not.toContain(first.tokenHash);
  });
});

describe("organization roles", () => {
  it("orders owner above admin above member", () => {
    expect(hasRequiredRole("owner", "admin")).toBe(true);
    expect(hasRequiredRole("admin", "member")).toBe(true);
    expect(hasRequiredRole("member", "admin")).toBe(false);
    expect(hasRequiredRole("admin", "owner")).toBe(false);
  });
});

describe("server configuration", () => {
  it("uses safe local defaults", () => {
    expect(loadServerConfig({})).toEqual({
      host: "127.0.0.1",
      port: 3000,
      sessionTtlSeconds: 604800,
      logLevel: "info",
    });
  });

  it("rejects invalid ports and session lifetimes", () => {
    expect(() => loadServerConfig({ PORT: "70000" })).toThrow(/PORT/);
    expect(() => loadServerConfig({ SESSION_TTL_SECONDS: "10" })).toThrow(/SESSION_TTL_SECONDS/);
  });
});
