/** A fresh idempotency key for one analyst decision. The backend accepts 16 to 64 characters of
 *  letters, digits, "_" and "-". The same key is reused when a request is retried after a network
 *  failure, so a decision that did reach the server is never recorded twice. */
export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return `ui-${c.randomUUID()}`;
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === "function") c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  return `ui-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}
