/** Optional per-tab storage for the analyst token. sessionStorage can throw (private mode,
 *  blocked storage) or be empty, so every access is guarded. Never localStorage: the token is
 *  forgotten when the tab closes. */
const KEY = "rs_analyst_token";

export function readToken(): string {
  try {
    return window.sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function writeToken(value: string | null): void {
  try {
    if (value) window.sessionStorage.setItem(KEY, value);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: the token simply is not remembered */
  }
}
