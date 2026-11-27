import { randomBytes, scrypt, timingSafeEqual } from "node:crypto";

const KEY_LENGTH = 64;
const SALT_LENGTH = 16;
const COST = 16384;
const BLOCK_SIZE = 8;
const PARALLELIZATION = 1;
const MAX_MEMORY = 64 * 1024 * 1024;
const OPTIONS = { N: COST, r: BLOCK_SIZE, p: PARALLELIZATION, maxmem: MAX_MEMORY };

function derive(password: string, salt: Buffer): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scrypt(password, salt, KEY_LENGTH, OPTIONS, (error, derived) => {
      if (error) {
        reject(error);
        return;
      }
      resolve(derived);
    });
  });
}

function encode(buffer: Buffer): string {
  return buffer.toString("base64url");
}

function decode(value: string, expectedLength: number): Buffer | undefined {
  const buffer = Buffer.from(value, "base64url");
  if (buffer.length !== expectedLength || encode(buffer) !== value) {
    return undefined;
  }
  return buffer;
}

function format(salt: Buffer, derived: Buffer): string {
  return `scrypt$${COST}$${BLOCK_SIZE}$${PARALLELIZATION}$${encode(salt)}$${encode(derived)}`;
}

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(SALT_LENGTH);
  return format(salt, await derive(password, salt));
}

export async function verifyPassword(password: string, stored: string | null): Promise<boolean> {
  const parts = (stored ?? "").split("$");
  if (parts.length !== 6 || parts[0] !== "scrypt") {
    await derive(password, Buffer.alloc(SALT_LENGTH));
    return false;
  }

  const [, cost, blockSize, parallelization, saltPart, hashPart] = parts;
  const salt = saltPart ? decode(saltPart, SALT_LENGTH) : undefined;
  const expected = hashPart ? decode(hashPart, KEY_LENGTH) : undefined;
  if (
    !salt ||
    !expected ||
    Number(cost) !== COST ||
    Number(blockSize) !== BLOCK_SIZE ||
    Number(parallelization) !== PARALLELIZATION
  ) {
    await derive(password, Buffer.alloc(SALT_LENGTH));
    return false;
  }

  return timingSafeEqual(await derive(password, salt), expected);
}

export async function verifyUnusablePassword(password: string): Promise<void> {
  await derive(password, Buffer.alloc(SALT_LENGTH));
}
