import { useCallback, useEffect, useState } from "react";

// ---- Edit these before publishing ----
const CONTACT = {
  name: "Vrashabh Kambalyal",
  role: "Full-stack developer, Bengaluru, India",
  email: "vvkam17@gmail.com",
  phone: "+91 9867768779", // remove this line's value if the page goes public
  linkedin: "https://www.linkedin.com/in/vrashabh-k",
  github: "https://github.com/vrashabh-k",
  grafana: "http://localhost:3000",
};

const GLOSSARY = [
  ["Service", "A small program that does one job, e.g. Payments charges cards. Several services together make up an application."],
  ["Response time (slowest 5%)", "How long customers wait. We show the time that 95% of requests beat, because slow requests are what users notice. Technical name: p95 latency."],
  ["Failed requests", "The share of requests that returned an error instead of a result. Technical name: error rate."],
  ["Normal", "What this service looked like over the last 15 minutes. The system learns it by itself, so no manual limits are needed."],
  ["Deviation score", "How far the current value is from normal. Near 0 is normal; above 4 raises an alert; 30 means something is clearly wrong. Technical name: z-score."],
  ["Warning / Critical", "Warning: clearly unusual. Critical: unusual by a large margin, or both response time and errors look wrong together."],
  ["Likely cause", "If a service depends on another that is also failing, the dependency is the probable root cause and the other is only a victim."],
];

const ms = (s) => (s == null ? "-" : `${(s * 1000).toFixed(0)} ms`);
const pct = (x) => (x == null ? "-" : `${(x * 100).toFixed(1)}%`);
const clock = (t) => (t ? new Date(t * 1000).toLocaleTimeString() : "-");
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const post = (url, body) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function tone(svc) {
  if (!svc) return "info";
  if (svc.status === "anomaly") return svc.severity;
  return svc.status === "ok" ? "ok" : "info";
}
const label = (svc) =>
  svc.status === "anomaly" ? `${cap(svc.severity)} issue`
  : svc.status === "ok" ? "Healthy"
  : svc.status === "insufficient_data" ? "Learning normal" : "Waiting for data";

function Chart({ data, field, normal, fmt, events }) {
  if (!data || data.length < 2) return <div className="chart empty">Collecting data...</div>;
  const W = 300, H = 90, vals = data.map((d) => d[field]);
  const max = Math.max(...vals, (normal || 0) * 1.5, field === "error" ? 0.05 : 0.05);
  const t0 = data[0].t, t1 = data[data.length - 1].t;
  const x = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
  const y = (v) => H - 4 - (v / max) * (H - 12);
  const line = data.map((d) => `${x(d.t).toFixed(1)},${y(d[field]).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" preserveAspectRatio="none">
      {events.map((e) => {
        const a = Math.max(x(e.started_at), 0), b = Math.min(e.ended_at ? x(e.ended_at) : W, W);
        return b > a ? <rect key={e.id} x={a} width={b - a} y="0" height={H} className="shade" /> : null;
      })}
      {normal != null && <line x1="0" x2={W} y1={y(normal)} y2={y(normal)} className="normal-line" />}
      <polyline points={line} className="series" />
      <text x="3" y="10" className="axis">{fmt(max)}</text>
    </svg>
  );
}

function ServiceCard({ svc, history, events, topology, byName }) {
  const cur = svc.current || {}, base = svc.baseline || {};
  const mine = events.filter((e) => e.service === svc.service);
  const downstream = topology.dependencies.filter(([a]) => a === svc.service).map(([, b]) => b);
  const cause = svc.status === "anomaly" ? downstream.filter((d) => byName[d]?.status === "anomaly") : [];
  const left = svc.required ? Math.max(0, svc.required - svc.points) * 5 : 0;
  return (
    <div className={`card ${svc.status === "anomaly" ? "card-alert" : ""}`}>
      <div className="card-head"><h3>{cap(svc.service)}</h3><span className={`badge ${tone(svc)}`}>{label(svc)}</span></div>
      {svc.status === "insufficient_data" && (
        <div className="learn">
          <div className="bar"><div style={{ width: `${(svc.points / svc.required) * 100}%` }} /></div>
          <p className="muted">Learning what normal looks like: {svc.points} of {svc.required} readings (about {Math.ceil(left / 60)} min left). Alerts start after this.</p>
        </div>
      )}
      {cause.length > 0 && <p className="cause">Likely cause: <b>{cause.map(cap).join(", ")}</b> (this service depends on it)</p>}
      {cur.latency_p95 != null && (<>
        <div className="metric"><span title="Time that 95% of requests beat">Response time (slowest 5%)</span>
          <b>{ms(cur.latency_p95)}</b><i>normal {ms(base.latency_p95)}</i></div>
        <Chart data={history} field="latency" normal={base.latency_p95} fmt={ms} events={mine} />
        <div className="metric"><span title="Share of requests that returned an error">Failed requests</span>
          <b>{pct(cur.error_rate)}</b><i>normal {pct(base.error_rate)}</i></div>
        <Chart data={history} field="error" normal={base.error_rate} fmt={pct} events={mine} />
        <p className="legend">Last 15 min. Dashed line = normal. Shaded = issue detected.</p>
      </>)}
      {svc.reasons?.length > 0 && <ul className="reasons">{svc.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
    </div>
  );
}

function Topology({ topology, byName }) {
  const targets = new Set(topology.dependencies.map(([, b]) => b));
  const entry = topology.services.filter((s) => !targets.has(s));
  const deps = topology.services.filter((s) => targets.has(s));
  const Node = ({ n }) => <div className={`node ${tone(byName[n])}`}>{cap(n)}</div>;
  return (
    <div className="topo">
      <div className="col"><div className="node plain">Customers</div></div><span className="arrow">→</span>
      <div className="col">{entry.map((n) => <Node key={n} n={n} />)}</div><span className="arrow">→</span>
      <div className="col">{deps.map((n) => <Node key={n} n={n} />)}</div>
    </div>
  );
}

export default function App() {
  const [services, setServices] = useState([]);
  const [events, setEvents] = useState([]);
  const [topology, setTopology] = useState({ services: [], dependencies: [] });
  const [faults, setFaults] = useState({});
  const [history, setHistory] = useState({});
  const [error, setError] = useState("");
  const [form, setForm] = useState({ svc: "payments", kind: "slow", dur: 60 });
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState(null);
  const [note, setNote] = useState("");
  const [now, setNow] = useState(Date.now());

  const byName = Object.fromEntries(services.map((s) => [s.service, s]));
  const load = useCallback(async () => {
    try {
      const [s, e, f] = await Promise.all(["status", "anomalies", "faults"].map((p) => fetch(`/api/${p}`).then((r) => r.json())));
      setServices(s); setEvents(e); setFaults(f); setError("");
    } catch { setError("Cannot reach the detector API. It may still be starting."); }
  }, []);
  useEffect(() => { fetch("/api/topology").then((r) => r.json()).then(setTopology).catch(() => {}); }, []);
  useEffect(() => { load(); const id = setInterval(load, 3000); return () => clearInterval(id); }, [load]);
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  useEffect(() => {
    const pull = () => topology.services.forEach((s) =>
      fetch(`/api/history/${s}`).then((r) => r.json()).then((d) => setHistory((h) => ({ ...h, [s]: d }))).catch(() => {}));
    pull(); const id = setInterval(pull, 5000); return () => clearInterval(id);
  }, [topology]);

  // Track the test: when was it noticed, when did it clear
  useEffect(() => {
    if (!test) return;
    const s = byName[test.svc], f = faults[test.svc];
    if (!test.detectedAt && s?.status === "anomaly") setTest((t) => ({ ...t, detectedAt: Date.now() }));
    if (test.detectedAt && !test.clearedAt && !(f?.remaining_s > 0) && s?.status === "ok") setTest((t) => ({ ...t, clearedAt: Date.now() }));
  }, [services, faults]); // eslint-disable-line

  const start = async () => {
    setBusy(true); setNote("");
    const body = form.kind === "slow" ? { latency_ms: 400, duration_s: form.dur } : { error_rate: 0.4, duration_s: form.dur };
    try { await post(`/api/chaos/${form.svc}`, body); setTest({ ...form, startedAt: Date.now() }); await load(); }
    catch { setNote("Could not start the test. Is the detector running?"); }
    setBusy(false);
  };
  const stop = async () => {
    setBusy(true);
    try { await post(`/api/chaos/${form.svc}`, { latency_ms: 0, error_rate: 0, duration_s: 0 }); await load();
      setNote(`Test on ${cap(form.svc)} stopped now. Traffic is normal again; the status clears in about 30 seconds because it is measured over a 30-second window.`); }
    catch { setNote("Could not stop the test."); }
    setBusy(false);
  };

  const bad = services.filter((s) => s.status === "anomaly");
  const roots = bad.filter((s) => !topology.dependencies.some(([a, b]) => a === s.service && byName[b]?.status === "anomaly"));
  const learning = services.some((s) => s.status === "insufficient_data");
  const summary = bad.length ? "issue" : learning ? "info" : "ok";
  const secs = (a, b) => Math.round((b - a) / 1000);
  const active = Object.entries(faults).filter(([, f]) => f?.remaining_s > 0);
  const what = form.kind === "slow" ? "adds 400 ms of delay to every request" : "makes 40% of requests fail";

  return (
    <main>
      <header><h1>Service Health Monitor</h1>
        <p className="muted">Live view of how our services are performing, and whether anything is behaving unusually compared with its own normal.</p></header>
      {error && <div className="banner err">{error}</div>}

      <div className={`banner ${summary}`}>
        {bad.length ? <><b>{bad.length} of {services.length} services affected.</b> Most likely root cause: <b>{roots.map((r) => cap(r.service)).join(", ")}</b>.</>
          : learning ? <b>Learning normal behaviour... alerts begin once enough readings are collected.</b>
          : <b>All {services.length} services are operating normally.</b>}
      </div>

      <section><h2>How services connect</h2>
        <p className="muted">When Customers use the site, the first service calls the others. A problem in a later box can slow down the one before it.</p>
        <Topology topology={topology} byName={byName} /></section>

      <section className="grid">{services.map((s) => <ServiceCard key={s.service} svc={s} history={history[s.service]} events={events} topology={topology} byName={byName} />)}</section>

      <section className="panel"><h2>Run a failure test</h2>
        <p className="muted">Safely simulate a problem to see how it is detected. This only affects the practice traffic generated by this demo.</p>
        <div className="form">
          <label>Service<select value={form.svc} onChange={(e) => setForm({ ...form, svc: e.target.value })}>{topology.services.map((s) => <option key={s} value={s}>{cap(s)}</option>)}</select></label>
          <label>Problem<select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="slow">Slow responses</option><option value="errors">Failing requests</option></select></label>
          <label>Lasts<select value={form.dur} onChange={(e) => setForm({ ...form, dur: +e.target.value })}>{[30, 60, 120].map((d) => <option key={d} value={d}>{d} seconds</option>)}</select></label>
        </div>
        <p className="explain">This test <b>{what}</b> in <b>{cap(form.svc)}</b> for <b>{form.dur} seconds</b>, then stops by itself.</p>
        <div className="actions">
          <button disabled={busy} onClick={start}>{busy ? "Working..." : "Start test"}</button>
          <button className="ghost" disabled={busy} onClick={stop}>Stop test now</button>
        </div>
        <p className="muted small">"Stop test now" ends the test on the selected service immediately. You never need it for the test to end; it is only for stopping early.</p>
        {note && <p className="note">{note}</p>}
        {active.map(([n, f]) => <p key={n} className="note live">● Test running on {cap(n)}: {f.latency_ms ? `+${f.latency_ms} ms delay` : `${Math.round(f.error_rate * 100)}% requests failing`}, ends in {f.remaining_s}s</p>)}
        {test && (<ol className="steps">
          <li className="done">Test started on {cap(test.svc)} <i>({secs(test.startedAt, now)}s ago)</i></li>
          <li className={test.detectedAt ? "done" : "wait"}>{test.detectedAt ? `Detected after ${secs(test.startedAt, test.detectedAt)}s` : "Waiting for the detector to notice (usually 10 to 15 seconds)..."}</li>
          <li className={test.clearedAt ? "done" : "wait"}>{test.clearedAt ? "Back to normal" : "Waiting for the test to end and metrics to settle (about 30 seconds after it ends)..."}</li>
        </ol>)}
      </section>

      <section><h2>Incident history</h2>
        {events.length === 0 ? <p className="muted">No issues detected yet.</p> :
          <table className="events"><thead><tr><th>#</th><th>Service</th><th>Severity</th><th>Started</th><th>Ended</th><th>What happened</th></tr></thead>
            <tbody>{events.map((e) => <tr key={e.id}><td>{e.id}</td><td>{cap(e.service)}</td><td><span className={`badge ${e.severity}`}>{e.severity}</span></td><td>{clock(e.started_at)}</td><td>{e.ended_at ? clock(e.ended_at) : "ongoing"}</td><td>{e.reasons.join("; ")}</td></tr>)}</tbody></table>}
      </section>

      <section><h2>What am I looking at?</h2>
        <dl>{GLOSSARY.map(([t, d]) => <div key={t}><dt>{t}</dt><dd>{d}</dd></div>)}</dl>
        <p className="muted">Need the raw numbers? <a href={CONTACT.grafana} target="_blank" rel="noreferrer">Open the detailed Grafana charts</a>.</p></section>

      <footer className="panel"><h2>About &amp; contact</h2>
        <p>Built by <b>{CONTACT.name}</b> — {CONTACT.role}. Python, Prometheus, Grafana, scikit-learn, React and Docker.</p>
        <p><a href={`mailto:${CONTACT.email}`}>{CONTACT.email}</a>{CONTACT.phone && <> · {CONTACT.phone}</>} · <a href={CONTACT.linkedin} target="_blank" rel="noreferrer">LinkedIn</a> · <a href={CONTACT.github} target="_blank" rel="noreferrer">GitHub</a></p></footer>
    </main>
  );
}
