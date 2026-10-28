export type Profile = { subject: string; roles: string[]; tenant_ids: string[] };
export type Api = <T>(path: string, body?: unknown) => Promise<T>;

export function createApi(token: string): Api {
  return async <T>(path: string, body?: unknown): Promise<T> => {
    const response = await fetch(`/api${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      redirect: 'error',
      cache: 'no-store',
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error('Sesja wygasła. Zaloguj się ponownie.');
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : `Nie udało się wykonać operacji (${response.status}). Sprawdź pola formularza.`);
    }
    return response.json() as Promise<T>;
  };
}
