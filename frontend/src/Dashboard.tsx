import { FormEvent, useEffect, useRef, useState } from 'react';
import { Api, Profile } from './api';

type Tenant = { id: string; name: string };
type Device = { id: string; hostname: string; os_version: string; online: boolean; revoked: boolean; last_seen: number; gateway_id: string | null };
type Definition = { id: string; name: string; kind: string; spec: { url?: string; sha256?: string; script?: string; arguments?: string[] }; status: string; created_by: string; approved_by: string | null; timeout_seconds: number };
type Job = { id: string; device_id: string; definition_id: string | null; kind: string; state: string; created_at: number; output: string | null; exit_code: number | null };
type Gateway = { id: string; name: string; revoked: boolean };
type Audit = { id: string; created_at: number; actor: string; action: string; target: string };
const labels: Record<string, string> = { online: 'Online', offline: 'Offline', queued: 'W kolejce', running: 'W trakcie', succeeded: 'Zakończone', failed: 'Błąd', unknown: 'Do weryfikacji', cancelled: 'Anulowane', approved: 'Zatwierdzony', draft: 'Do zatwierdzenia', revoked: 'Wycofany' };
const date = (timestamp: number) => new Date(timestamp * 1000).toLocaleString('pl-PL');
const badge = (state: string) => <span className={`badge ${state}`}>{labels[state] ?? state}</span>;

export function Dashboard({ api, profile, onLogout }: { api: Api; profile: Profile; onLogout: () => void }) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenant, setTenant] = useState('');
  const [tab, setTab] = useState('Komputery');
  const [devices, setDevices] = useState<Device[]>([]);
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [gateways, setGateways] = useState<Gateway[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [definitionId, setDefinitionId] = useState('');
  const [secret, setSecret] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [inspect, setInspect] = useState<Definition | Job>();
  const [page, setPage] = useState(0);
  const currentTenant = useRef(tenant);
  currentTenant.current = tenant;
  const administrator = profile.roles.includes('platform_admin');
  const writer = administrator || profile.roles.includes('operator');
  const approver = administrator || profile.roles.includes('approver');
  const base = `/tenants/${tenant}`;

  async function loadClients() {
    const result = await api<Tenant[]>('/tenants');
    setTenants(result);
    setTenant(previous => previous || result[0]?.id || '');
  }
  useEffect(() => { loadClients().catch(exception => setError(exception.message)); }, []);
  async function refresh() {
    if (!tenant) return;
    const captured = tenant;
    const [deviceRows, definitionRows, jobRows, gatewayRows, auditRows] = await Promise.all([
      api<Device[]>(`${base}/devices?offset=${tab === 'Komputery' ? page * 200 : 0}`),
      api<Definition[]>(`${base}/definitions`), api<Job[]>(`${base}/jobs?offset=${tab === 'Zadania' ? page * 200 : 0}`),
      api<Gateway[]>(`${base}/gateways`), api<Audit[]>(`${base}/audit?offset=${tab === 'Audyt' ? page * 200 : 0}`),
    ]);
    if (currentTenant.current !== captured) return;
    setDevices(deviceRows); setDefinitions(definitionRows); setJobs(jobRows); setGateways(gatewayRows); setAudit(auditRows);
  }
  useEffect(() => {
    setSelected([]); setSecret(''); setDefinitionId(''); setInspect(undefined); setError(''); setNotice('');
    setDevices([]); setDefinitions([]); setJobs([]); setGateways([]); setAudit([]);
  }, [tenant]);
  useEffect(() => {
    refresh().catch(exception => setError(exception.message));
    const timer = window.setInterval(() => refresh().catch(exception => setError(exception.message)), 15000);
    return () => window.clearInterval(timer);
  }, [tenant, page, tab]);

  async function action(operation: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); setNotice(success); await refresh(); }
    catch (exception) { setError(exception instanceof Error ? exception.message : 'Operacja nie powiodła się.'); }
    finally { setBusy(false); }
  }
  const submit = (event: FormEvent<HTMLFormElement>, operation: (data: FormData) => Promise<unknown>, success: string) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void action(async () => { await operation(data); form.reset(); }, success);
  };
  const chooseTenant = (value: string) => { currentTenant.current = value; setTenant(value); setPage(0); };
  const navigate = (value: string) => { setTab(value); setPage(0); setSelected([]); };
  const approved = definitions.filter(definition => definition.status === 'approved');
  const online = devices.filter(device => device.online).length;
  return <div className="shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">+</span><div>PC MED<small>CONTROL CENTER</small></div></div><p className="nav-label">ZARZĄDZANIE</p><nav>{['Komputery', 'Zadania', 'Biblioteka', 'Komunikaty', 'Bramki LAN', 'Audyt'].map((item, index) => <button key={item} className={tab === item ? 'active' : ''} onClick={() => navigate(item)}><span aria-hidden>{['▦', '◷', '▤', '◻', '⇄', '≡'][index]}</span>{item}</button>)}</nav><div className="sidebar-foot"><span className="dot" /> Sieć prywatna VPN<small>PC MED RMM · MVP 0.1</small><button className="secondary" onClick={onLogout}>Wyloguj</button></div></aside>
    <div className="workspace"><header className="topbar"><span>Przestrzeń robocza <b>/ {tab}</b></span><label>Klient<select aria-label="Klient" value={tenant} disabled={busy} onChange={event => chooseTenant(event.target.value)}><option value="" disabled>Wybierz klienta</option>{tenants.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><span className="avatar" title={profile.roles.join(', ')}>PM</span></header>
      <main><div className="page-heading"><div><p className="eyebrow">{tenants.find(item => item.id === tenant)?.name ?? 'TWÓJ PANEL'}</p><h1>{tab}</h1><p>{({ Komputery: 'Stan urządzeń i operacje dla wybranego klienta.', Zadania: 'Przebieg operacji, wyniki i historia wykonań.', Biblioteka: 'Sprawdzone instalatory i zatwierdzone skrypty.', Komunikaty: 'Wiadomości dla zalogowanych użytkowników Windows.', 'Bramki LAN': 'Jeden komputer z VPN. Dostęp dla całej sieci klienta.', Audyt: 'Ślad operacji wykonanych w przestrzeni klienta.' } as Record<string, string>)[tab]}</p></div><button className="secondary" disabled={!tenant || busy} onClick={() => void action(refresh, 'Dane odświeżone.')}>↻ Odśwież</button></div>
      {error && <div className="error" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}
      {administrator && <details className="client-create"><summary>Dodaj klienta</summary><form className="inline" onSubmit={event => submit(event, async data => { const created = await api<Tenant>('/tenants', { name: data.get('name') }); await loadClients(); chooseTenant(created.id); }, 'Klient utworzony. Nadaj użytkownikom jego identyfikator w dostawcy logowania.')}><label>Nazwa klienta<input name="name" required maxLength={120} /></label><button disabled={busy}>Utwórz klienta</button></form></details>}
      {!tenant && <div className="empty">Utwórz klienta lub poproś administratora o nadanie dostępu.</div>}
      {tenant && <>
      {tab === 'Komputery' && <><section className="stats"><article><span>Urządzenia na stronie</span><strong>{devices.length}</strong><small>W przestrzeni klienta</small></article><article><span>Online</span><strong className="teal">{online}<i className="dot" /></strong><small>Kontakt w ostatnich 90 sekundach</small></article><article><span>Zadania w trakcie</span><strong>{jobs.filter(job => job.state === 'running').length}</strong><small>Wśród ostatnich 200 zadań</small></article></section>
        <section className="panel"><div className="panel-heading"><h2>Urządzenia Windows</h2>{writer && <button disabled={busy} onClick={() => void action(async () => { const result = await api<{ token: string; expires_at: number }>(`${base}/enrollments`, {}); setSecret(`Token rejestracji (jednorazowy, ważny do ${date(result.expires_at)}):\n${result.token}`); }, 'Token wyświetlony poniżej.')}>+ Zarejestruj komputer</button>}</div>
        <div className="table-wrap"><table><thead><tr><th>Wybierz</th><th>Komputer</th><th>Status</th><th>Połączenie</th><th>Ostatni kontakt</th><th /></tr></thead><tbody>{devices.map(device => <tr key={device.id}><td><input type="checkbox" aria-label={`Wybierz ${device.hostname}`} disabled={device.revoked || !writer || busy} checked={selected.includes(device.id)} onChange={event => setSelected(previous => event.target.checked ? [...previous, device.id] : previous.filter(id => id !== device.id))} /></td><td><b>{device.hostname}</b><small>{device.os_version}</small></td><td>{badge(device.revoked ? 'revoked' : device.online ? 'online' : 'offline')}</td><td>{device.gateway_id ? 'Bramka LAN' : 'Bezpośrednie VPN'}</td><td>{date(device.last_seen)}</td><td>{writer && !device.revoked && <button className="text-button danger" disabled={busy} onClick={() => window.confirm(`Unieważnić agenta ${device.hostname}?`) && void action(() => api(`${base}/devices/${device.id}/revoke`, {}), 'Agent unieważniony.')}>Unieważnij</button>}</td></tr>)}</tbody></table>{!devices.length && <div className="empty">Brak urządzeń. Wygeneruj token i zarejestruj pierwszego agenta.</div>}</div>
        {writer && <div className="batch"><span>Wybrano: <b>{selected.length}</b></span><select aria-label="Zatwierdzona definicja" value={definitionId} onChange={event => setDefinitionId(event.target.value)}><option value="">Wybierz zatwierdzoną operację</option>{approved.map(definition => <option value={definition.id} key={definition.id}>{definition.name} · {definition.kind}</option>)}</select><button disabled={busy || !selected.length || !definitionId} onClick={() => window.confirm(`Uruchomić „${approved.find(definition => definition.id === definitionId)?.name}” na ${selected.length} komputerach?`) && void action(() => api(`${base}/jobs`, { device_ids: selected, definition_id: definitionId }), 'Zadania dodane do kolejki.')}>Uruchom na wybranych →</button></div>}</section></>}
      {tab === 'Zadania' && <section className="panel"><div className="panel-heading"><h2>Historia operacji</h2><span>Wynik „Do weryfikacji” wymaga sprawdzenia urządzenia</span></div><div className="table-wrap"><table><thead><tr><th>Operacja</th><th>Komputer</th><th>Stan</th><th>Utworzono</th><th>Wynik</th></tr></thead><tbody>{jobs.map(job => <tr key={job.id}><td><b>{definitions.find(definition => definition.id === job.definition_id)?.name ?? job.kind}</b><small>{job.id}</small></td><td>{devices.find(device => device.id === job.device_id)?.hostname ?? job.device_id}</td><td>{badge(job.state)}</td><td>{date(job.created_at)}</td><td><button className="text-button" onClick={() => setInspect(job)}>Szczegóły</button>{writer && job.state === 'queued' && <button className="text-button danger" disabled={busy} onClick={() => void action(() => api(`${base}/jobs/${job.id}/cancel`, {}), 'Zadanie anulowane.')}>Anuluj</button>}</td></tr>)}</tbody></table>{!jobs.length && <div className="empty">Historia pojawi się po zleceniu pierwszej operacji.</div>}</div></section>}
      {tab === 'Biblioteka' && <div className="split"><section className="panel"><div className="panel-heading"><h2>Definicje operacji</h2></div>{definitions.map(definition => <article className="definition" key={definition.id}><div><span className="type">{definition.kind.toUpperCase()}</span><b>{definition.name}</b>{badge(definition.status)}</div><small>Limit: {definition.timeout_seconds}s · wersja {definition.id.slice(0, 8)}</small><button className="text-button" onClick={() => setInspect(definition)}>Sprawdź treść i zatwierdzenie →</button></article>)}{!definitions.length && <div className="empty">Dodaj instalator lub skrypt do przeglądu.</div>}</section>
        {writer && <section className="panel form-panel"><h2>Nowa definicja</h2><p>Po zapisaniu treść jest niezmienna. Wykonanie wymaga zatwierdzenia przez inną osobę.</p><form onSubmit={event => submit(event, async data => { const kind = String(data.get('kind')); return api(`${base}/definitions`, { name: data.get('name'), kind, timeout_seconds: Number(data.get('timeout')), ...(kind === 'bat' || kind === 'powershell' ? { script: data.get('script') } : { url: data.get('url'), sha256: data.get('sha256'), arguments: JSON.parse(String(data.get('arguments') || '[]')) }) }); }, 'Definicja czeka na zatwierdzenie.')}><label>Nazwa<input name="name" required maxLength={120} /></label><label>Typ<select name="kind"><option value="powershell">PowerShell</option><option value="bat">BAT</option><option value="msi">MSI</option><option value="exe">EXE</option></select></label><label>Limit czasu (sekundy)<input name="timeout" type="number" defaultValue={600} min={10} max={3600} required /></label><label>Treść skryptu (BAT / PowerShell)<textarea name="script" maxLength={65536} rows={6} spellCheck={false} /></label><label>Adres HTTPS instalatora (MSI / EXE)<input name="url" type="url" placeholder="https://packages.example.test/app.msi" /></label><label>SHA-256 instalatora<input name="sha256" maxLength={64} /></label><label>Argumenty instalatora jako tablica JSON<input name="arguments" defaultValue="[]" /></label><button disabled={busy}>Zapisz do przeglądu</button></form></section>}</div>}
      {tab === 'Komunikaty' && <section className="panel form-panel message-form"><span className="type">WIADOMOŚCI WINDOWS</span><h2>Poinformuj użytkowników</h2><p>Komunikat trafi do jednej aktywnej sesji użytkownika na każdym wybranym komputerze. Potwierdzamy dostarczenie do modułu UI.</p>{writer ? <form onSubmit={event => submit(event, data => api(`${base}/messages`, { title: data.get('title'), body: data.get('body'), device_ids: data.getAll('devices') }), 'Komunikaty dodane do kolejki.')}><label>Tytuł<input name="title" required maxLength={120} placeholder="Planowana przerwa techniczna" /></label><label>Treść<textarea name="body" required maxLength={4000} rows={6} /></label><fieldset><legend>Odbiorcy (urządzenia z bieżącej pierwszej strony)</legend>{devices.filter(device => !device.revoked).map(device => <label className="check" key={device.id}><input name="devices" type="checkbox" value={device.id} />{device.hostname}</label>)}</fieldset><button disabled={busy}>Wyślij komunikat →</button></form> : <p>Wysyłanie wymaga roli operatora.</p>}</section>}
      {tab === 'Bramki LAN' && <div className="split"><section className="panel"><div className="panel-heading"><h2>Bramki klienta</h2></div><div className="topology"><span>Centrala</span><b>VPN ⇄ HTTPS</b><span>Bramka LAN</span><b>HTTPS ⇄</b><span>Agenci Windows</span></div>{gateways.map(gateway => <article className="definition" key={gateway.id}><b>{gateway.name}</b>{badge(gateway.revoked ? 'revoked' : 'approved')}<small>{gateway.id}</small>{writer && !gateway.revoked && <button className="text-button danger" disabled={busy} onClick={() => window.confirm('Unieważnić bramkę? Podłączone urządzenia stracą łączność z centralą.') && void action(() => api(`${base}/gateways/${gateway.id}/revoke`, {}), 'Bramka unieważniona.')}>Unieważnij bramkę</button>}</article>)}</section>{writer && <section className="panel form-panel"><h2>Dodaj bramkę</h2><p>Zainstaluj usługę Gateway na komputerze połączonym z VPN. Pozostałym agentom ustaw lokalny adres HTTPS tej bramki.</p><form onSubmit={event => submit(event, async data => { const result = await api<{ token: string; id: string }>(`${base}/gateways`, { name: data.get('name') }); setSecret(`Token bramki ${result.id} (pokazywany tylko teraz):\n${result.token}`); }, 'Bramka utworzona. Skonfiguruj usługę Windows.')}><label>Nazwa bramki<input name="name" required maxLength={120} /></label><button disabled={busy}>Utwórz i pokaż token</button></form></section>}</div>}
      {tab === 'Audyt' && <section className="panel"><div className="panel-heading"><h2>Dziennik zdarzeń</h2><span>Ostatnie zdarzenia · bez sekretów i treści wyników</span></div><div className="table-wrap"><table><thead><tr><th>Czas</th><th>Operacja</th><th>Wykonawca</th><th>Obiekt</th></tr></thead><tbody>{audit.map(event => <tr key={event.id}><td>{date(event.created_at)}</td><td><b>{event.action}</b></td><td className="mono">{event.actor}</td><td className="mono">{event.target}</td></tr>)}</tbody></table></div></section>}
      {['Komputery', 'Zadania', 'Audyt'].includes(tab) && <div className="pagination"><button className="secondary" disabled={page === 0} onClick={() => { setPage(page - 1); setSelected([]); }}>← Poprzednia</button><span>Strona {page + 1} · do 200 rekordów</span><button className="secondary" disabled={(tab === 'Komputery' ? devices : tab === 'Zadania' ? jobs : audit).length < 200} onClick={() => { setPage(page + 1); setSelected([]); }}>Następna →</button></div>}
      {secret && <section className="secret panel"><h2>Zapisz token w bezpiecznym miejscu</h2><p>Wprowadź go w lokalnym narzędziu konfiguracji usługi. Nie wysyłaj go w komunikatach ani zgłoszeniach.</p><textarea aria-label="Wygenerowany token" readOnly value={secret} rows={3} /><button className="secondary" onClick={() => setSecret('')}>Ukryj token</button></section>}
      <footer>PC MED <span>Identyfikator klienta: {tenant}</span><span>Odświeżanie co 15 s</span></footer></>}
      </main>
    </div>
    {inspect && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Szczegóły operacji"><button className="secondary close" onClick={() => setInspect(undefined)}>Zamknij ×</button>{'spec' in inspect ? <><h2>{inspect.name}</h2><p>{inspect.kind} · {badge(inspect.status)}</p><pre>{JSON.stringify(inspect.spec, null, 2)}</pre><p>Autor: {inspect.created_by}<br />Zatwierdził: {inspect.approved_by ?? '—'}</p>{approver && inspect.status === 'draft' && inspect.created_by !== profile.subject && <button disabled={busy} onClick={() => window.confirm('Potwierdzasz przegląd treści, argumentów i sumy SHA-256?') && void action(async () => { await api(`${base}/definitions/${inspect.id}/approve`, {}); setInspect(undefined); }, 'Definicja zatwierdzona.')}>Zatwierdź wykonanie</button>}{approver && inspect.status !== 'revoked' && <button className="secondary danger" disabled={busy} onClick={() => void action(async () => { await api(`${base}/definitions/${inspect.id}/revoke`, {}); setInspect(undefined); }, 'Definicja wycofana.')}>Wycofaj</button>}</> : <><h2>Wynik operacji</h2><p>{badge(inspect.state)} · kod wyjścia: {inspect.exit_code ?? '—'}</p><pre>{inspect.output ?? 'Wynik nie został jeszcze odebrany.'}</pre><small>{inspect.id}</small></>}</section></div>}
  </div>;
}
