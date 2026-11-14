/** Small fetch helpers with a timeout. No retries: a failure falls back to the snapshot. */

export class HttpError extends Error {
  constructor(
    message: string,
    public readonly status: number | null,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export async function getJson<T>(
  url: string,
  opts: { timeoutMs: number; headers?: Record<string, string> },
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs);
  try {
    const res = await fetch(url, { headers: opts.headers, signal: controller.signal, cache: "no-store" });
    if (!res.ok) throw new HttpError(`${res.status} from ${url}`, res.status);
    try {
      return (await res.json()) as T;
    } catch {
      throw new HttpError(`${url} did not return JSON`, res.status);
    }
  } catch (err) {
    if (err instanceof HttpError) throw err;
    if (controller.signal.aborted) throw new HttpError(`timed out after ${opts.timeoutMs} ms: ${url}`, null);
    throw new HttpError(`could not reach ${url}`, null);
  } finally {
    clearTimeout(timer);
  }
}
