export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed with status ${status}`);
    this.status = status;
  }
}

/**
 * Every admin route lives under /t/{slug}/... (see app/main.py). Auth
 * is the httpOnly `session` cookie set by /api/auth/login — fetch's
 * same-origin default already sends it, no header wiring needed here.
 */
export function useAdminApi(tenantSlug) {
  const base = `/t/${tenantSlug}`;

  async function api(path, options = {}) {
    const isForm = options.body instanceof FormData;
    const res = await fetch(base + path, {
      ...options,
      headers: isForm ? options.headers : { "Content-Type": "application/json", ...(options.headers || {}) },
    });

    const raw = await res.text();
    let data = null;
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        // Non-JSON body (shouldn't happen — main.py's exception
        // handler always returns JSON — but don't crash the caller
        // if it ever does).
      }
    }

    if (!res.ok) {
      if (res.status === 401) {
        window.dispatchEvent(new CustomEvent("supportlm-admin-unauthorized"));
      }
      throw new ApiError(res.status, data && data.detail);
    }
    return data;
  }

  return { api, base };
}
