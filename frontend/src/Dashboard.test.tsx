import React from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Dashboard } from './Dashboard';
import { Api, createApi } from './api';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test('changing client clears device selection and prevents stale client results', async () => {
  const api = vi.fn(async (path: string) => {
    if (path === '/tenants') return [{ id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }];
    if (path.includes('/devices')) return [{ id: path.includes('/a/') ? 'device-a' : 'device-b', hostname: path.includes('/a/') ? 'PC Alpha' : 'PC Beta', online: true, revoked: false, last_seen: 1, os_version: 'Windows' }];
    return [];
  }) as Api;
  render(<Dashboard api={api} profile={{ subject: 'operator', roles: ['operator'], tenant_ids: ['a', 'b'] }} onLogout={() => {}} />);
  const checkbox = await screen.findByRole('checkbox', { name: 'Wybierz PC Alpha' });
  fireEvent.click(checkbox);
  expect(checkbox).toBeChecked();
  fireEvent.change(screen.getByRole('combobox', { name: 'Klient' }), { target: { value: 'b' } });
  const other = await screen.findByRole('checkbox', { name: 'Wybierz PC Beta' });
  expect(other).not.toBeChecked();
  expect(screen.queryByText('PC Alpha')).not.toBeInTheDocument();
});

test('API sends bearer only to same-origin API and refuses redirects', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }));
  await createApi('secret')('/me');
  expect(fetchMock).toHaveBeenCalledWith('/api/me', expect.objectContaining({ redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer secret' } }));
});

test('expired login produces a clear error', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }));
  await expect(createApi('expired')('/me')).rejects.toThrow('Sesja wygasła');
});
