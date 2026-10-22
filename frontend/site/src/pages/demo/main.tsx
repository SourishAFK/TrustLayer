import { useEffect, useRef, useState } from 'react';
import { StackBar } from '../../components/charts';
import type { Look } from '../../components/FieldCanvas';
import { mount, Shell } from '../../components/Shell';
import { Aurora, Cta, Kicker, VerdictChip } from '../../fx/fx';
import { Alert, Arrow, ArrowUpRight, Check } from '../../fx/icons';
import { DemoUnavailable, openDemoStream, UNREACHABLE, type DemoBody } from '../../lib/api';
import { VERDICTS, type Verdict } from '../../lib/content';
import { gsap, reducedMotion, useGSAP } from '../../lib/motion';
import { PRESETS, presetFrom, type PresetId } from '../../lib/presets';
import { CITATION_LABEL, CLAIM_KIND, plainStage, segments, SOURCE_KIND, STAGES, type Claim, type Progress, type Report, type StreamLine } from '../../lib/report';
import answerRun from './recorded/answer.json';
import documentRun from './recorded/document.json';
import supportRun from './recorded/support.json';

type Recording = { recorded_at: string; lines: StreamLine[] };
const RECORDED = { answer: answerRun, document: documentRun, support: supportRun } as unknown as Record<PresetId, Recording>;

const LOOK: Look = {
  desktop: { x: -3.9, y: 1.6, scale: 0.6, tilt: -0.4, opacity: 0.45, morph: 0, speed: 1.4 },
  mobile: { x: 0, y: 2.4, scale: 0.34, tilt: -0.3, opacity: 0.3, morph: 0, speed: 1.4 },
};
const LIMITS = { answer: 3000, question: 500, key: 6000 };
const VERDICT_ORDER: Verdict[] = ['CONTRADICTED', 'DISPUTED', 'UNVERIFIED', 'SUPPORTED', 'NOT CHECKABLE'];
const COLOR: Record<Verdict, string> = {
  SUPPORTED: '#08a4c6', CONTRADICTED: '#d43126', DISPUTED: '#8e3eae', UNVERIFIED: '#b4901a', 'NOT CHECKABLE': '#8a90a2',
};

type StageState = Record<string, { status: string; message: string }>;
type Run = { phase: 'idle' | 'running' | 'done' | 'error'; stages: StageState; log: Progress[]; report?: Report; error?: string; recordedAt?: string; started?: number };

function useRunner() {
  const [run, setRun] = useState<Run>({ phase: 'idle', stages: {}, log: [] });
  const abort = useRef<AbortController | null>(null);

  const apply = (line: StreamLine) => setRun(r => {
    if (line.type === 'progress') {
      const e = line.event;
      const stages = e.type === 'stage' || STAGES.some(s => s.key === e.stage)
        ? { ...r.stages, [e.stage]: { status: e.status === 'progress' ? 'started' : e.status, message: e.message } } : r.stages;
      return { ...r, stages, log: [...r.log.slice(-40), e] };
    }
    if (line.type === 'report') return { ...r, phase: 'done', report: line.report };
    return { ...r, phase: 'error', error: line.message, recordedAt: undefined };
  });

  const replay = async (recording: Recording, signal: AbortSignal, reason: string) => {
    setRun({ phase: 'running', stages: {}, log: [], started: performance.now(), recordedAt: recording.recorded_at, error: reason });
    const total = Math.max(1, ...recording.lines.map(l => (l.type === 'progress' ? l.event.elapsed_ms : 0)));
    const scale = Math.min(1, 5500 / total); // replay at most ~5.5 seconds
    let last = 0;
    for (const line of recording.lines) {
      const at = line.type === 'progress' ? line.event.elapsed_ms * scale : last + 500;
      await new Promise(resolve => setTimeout(resolve, Math.max(0, at - last)));
      if (signal.aborted) return;
      last = at;
      apply(line);
    }
  };

  const start = async (body: DemoBody, preset: PresetId | null) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setRun({ phase: 'running', stages: {}, log: [], started: performance.now() });
    try {
      for await (const line of await openDemoStream(body, controller.signal)) {
        if (controller.signal.aborted) return;
        apply(line as StreamLine);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      const reason = err instanceof DemoUnavailable ? err.message : UNREACHABLE;
      if (preset && !(err instanceof DemoUnavailable && err.status === 422)) {
        await replay(RECORDED[preset], controller.signal, reason);
      } else {
        setRun({ phase: 'error', stages: {}, log: [], error: reason });
      }
    }
  };
  useEffect(() => () => abort.current?.abort(), []);
  return { run, start };
}

function Timeline({ run }: { run: Run }) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (run.phase !== 'running') return;
    const id = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(id);
  }, [run.phase]);
  const elapsed = run.started ? ((run.phase === 'running' ? now || run.started : performance.now()) - run.started) / 1000 : 0;
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="t-label flex items-center gap-2 text-ink-2">
          {run.phase === 'running' ? <span className="pulse-dot h-2 w-2 rounded-full bg-cyan shadow-[0_0_10px_#38d6ff]" /> : <Check className="h-4 w-4 text-ok" />}
          {run.phase === 'running' ? 'Checking' : 'Checked'}
        </span>
        <span className="font-mono text-xs tabular-nums text-muted">{Math.max(0, elapsed).toFixed(1)}s</span>
      </div>
      <ol className="mt-5 space-y-2" aria-live="polite">
        {STAGES.map(s => {
          const state = run.stages[s.key];
          const status = state?.status ?? 'waiting';
          return (
            <li key={s.key} className={`flex items-start gap-3 rounded-lg px-2 py-1.5 transition-colors ${status === 'started' ? 'bg-cyan/[0.07]' : ''}`}>
              <span className="mt-1 grid h-3.5 w-3.5 shrink-0 place-items-center">
                {status === 'completed' ? <Check className="h-3.5 w-3.5 text-ok" />
                  : status === 'started' ? <span className="h-3 w-3 animate-spin rounded-full border border-cyan border-t-transparent" />
                  : status === 'failed' ? <Alert className="h-3.5 w-3.5 text-bad" />
                  : <span className={`h-1.5 w-1.5 rounded-full ${status === 'skipped' ? 'bg-white/15' : 'bg-white/30'}`} />}
              </span>
              <span className="min-w-0">
                <span className={`block text-sm ${status === 'waiting' || status === 'skipped' ? 'text-muted' : 'text-ink'}`}>{s.label}{status === 'skipped' && <span className="text-muted"> · not needed</span>}</span>
                {state && plainStage(s.key, state.status, state.message) && <span className="block text-xs leading-snug text-muted">{plainStage(s.key, state.status, state.message)}</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ClaimCard({ claim, focused, onFocus }: { claim: Claim; focused: boolean; onFocus: () => void }) {
  const items = [...claim.contradictions, ...claim.evidence];
  return (
    <article id={`claim-${claim.claim_id}`} onMouseEnter={onFocus}
      className={`claim-card glass spotlight rounded-2xl p-5 [overflow-wrap:anywhere] transition-shadow ${focused ? 'shadow-[0_0_0_1px_rgb(56_214_255/0.5),0_0_40px_-10px_rgb(56_214_255/0.6)]' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <VerdictChip verdict={claim.verification_status} />
        <span className="t-label text-muted">{CLAIM_KIND[claim.claim_type] ?? 'Claim'}</span>
      </div>
      <p className="mt-4 font-serif text-xl leading-snug text-ink">“{claim.exact_text}”</p>
      <p className="mt-3 text-sm text-ink-2">{claim.explanation}</p>
      {claim.calculations.filter(c => !c.consistent).map(c => (
        <div key={c.expression} className="mt-4 rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 font-mono text-sm [overflow-wrap:anywhere]">
          <div className="text-muted">The math</div>
          <div className="mt-1 text-ink">{c.expression} = <b className="text-ink">{c.computed_value}</b>, not {c.stated_value}</div>
        </div>
      ))}
      {items.map(e => (
        <figure key={e.evidence_id} className={`mt-4 rounded-xl border px-4 py-3 ${e.stance === 'contradicts' ? 'border-bad/40 bg-bad/[0.07]' : 'border-ok/40 bg-ok/[0.07]'}`}>
          <blockquote className="text-sm leading-relaxed text-ink">“{e.quote}”</blockquote>
          <figcaption className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>{e.stance === 'contradicts' ? 'Contradicts' : 'Supports'} · {SOURCE_KIND[e.source_type] ?? e.source_type}</span>
            {e.url.startsWith('http')
              ? <a href={e.url} target="_blank" rel="noreferrer nofollow" className="inline-flex items-center gap-1 text-cyan hover:text-ice">{e.domain}<ArrowUpRight className="h-3 w-3" /></a>
              : <span>{e.title ?? e.domain}</span>}
          </figcaption>
        </figure>
      ))}
      {claim.suggested_correction && (
        <p className="mt-4 rounded-xl border border-line-2 bg-white/[0.03] px-4 py-3 text-sm"><span className="text-muted">Suggested fix: </span><span className="text-ink">{claim.suggested_correction}</span></p>
      )}
      {claim.limitations.length > 0 && (
        <details className="mt-3 text-xs text-muted">
          <summary className="cursor-pointer select-none">Limits of this verdict</summary>
          <ul className="mt-2 list-disc space-y-1 pl-4">{claim.limitations.map(l => <li key={l}>{l}</li>)}</ul>
        </details>
      )}
    </article>
  );
}

function Results({ report }: { report: Report }) {
  const root = useRef<HTMLDivElement>(null);
  const [focus, setFocus] = useState<string | null>(null);
  useGSAP(() => {
    if (reducedMotion()) return;
    gsap.from('.reveal-in', { y: 24, opacity: 0, filter: 'blur(6px)', stagger: 0.07, duration: 0.9 });
  }, { scope: root });
  const claims = [...report.claims].sort((a, b) => VERDICT_ORDER.indexOf(a.verification_status) - VERDICT_ORDER.indexOf(b.verification_status));
  const counts = VERDICT_ORDER.map(v => ({ v, n: report.claims.filter(c => c.verification_status === v).length }));
  return (
    <div ref={root} className="min-w-0 space-y-4 [overflow-wrap:anywhere]">
      <div className="reveal-in glass rounded-2xl p-5">
        <div className="t-label text-muted">Result</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {counts.filter(c => c.n).map(c => <VerdictChip key={c.v} verdict={c.v} label={`${c.n} ${VERDICTS[c.v].label.toLowerCase()}`} />)}
        </div>
        <div className="mt-5">
          <StackBar parts={counts.filter(c => c.n).map(c => ({ label: VERDICTS[c.v].label, value: c.n, color: COLOR[c.v], tip: `${c.n} ${VERDICTS[c.v].label.toLowerCase()}: ${VERDICTS[c.v].meaning}` }))} />
        </div>
      </div>
      <div className="reveal-in glass rounded-2xl p-5">
        <div className="t-label text-muted">The answer, claim by claim</div>
        <p className="mt-3 leading-[1.9] text-ink-2">
          {segments(report.response_text, report.claims).map((part, i) => part.claim ? (
            <a key={i} href={`#claim-${part.claim.claim_id}`} onMouseEnter={() => setFocus(part.claim!.claim_id)}
              className="rounded px-0.5 text-ink transition-colors"
              style={{ backgroundColor: `${COLOR[part.claim.verification_status]}${focus === part.claim.claim_id ? '44' : '22'}`, boxShadow: `inset 0 -2px 0 ${COLOR[part.claim.verification_status]}` }}>
              {part.text}
            </a>
          ) : <span key={i}>{part.text}</span>)}
        </p>
      </div>
      {claims.map(c => <div key={c.claim_id} className="reveal-in"><ClaimCard claim={c} focused={focus === c.claim_id} onFocus={() => setFocus(c.claim_id)} /></div>)}
      {report.citations.length > 0 && (
        <div className="reveal-in glass rounded-2xl p-5">
          <div className="t-label text-muted">Citations, opened one by one</div>
          <ul className="mt-4 space-y-3">
            {report.citations.map(c => {
              const look = CITATION_LABEL[c.status] ?? { label: c.status, tone: 'UNVERIFIED' as Verdict };
              return (
                <li key={c.citation_id} className="rounded-xl border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-xs text-ink">{c.url ?? c.doi ?? c.raw_text}</span>
                    <VerdictChip verdict={look.tone} label={look.label} />
                  </div>
                  <p className="mt-2 text-sm text-ink-2">{c.explanation}</p>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {report.signals.length > 0 && (
        <div className="reveal-in glass rounded-2xl p-5">
          <div className="t-label text-muted">Also noticed</div>
          <ul className="mt-4 space-y-3">
            {report.signals.map(s => (
              <li key={s.signal_id} className="flex gap-3 text-sm">
                <Alert className={`mt-0.5 h-4 w-4 shrink-0 ${s.severity === 'critical' ? 'text-bad' : 'text-warn'}`} />
                <span><span className="text-ink">“{s.text}”</span> <span className="text-ink-2">{s.explanation}</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(report.incomplete_checks.length > 0 || report.limitations.length > 0) && (
        <details className="reveal-in glass rounded-2xl p-5">
          <summary className="cursor-pointer select-none font-medium">What this check did not cover</summary>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-ink-2">
            {[...report.incomplete_checks, ...report.limitations].map(l => <li key={l}>{l}</li>)}
          </ul>
        </details>
      )}
      <p className="reveal-in px-1 font-mono text-xs text-muted">
        {(report.usage.duration_ms / 1000).toFixed(1)}s · {report.usage.model_calls} AI calls · {report.usage.search_calls} searches · {report.usage.pages_fetched} pages opened · about ${report.usage.estimated_cost_usd.toFixed(4)} · {report.privacy.stored ? 'stored' : 'not stored'}
      </p>
    </div>
  );
}

function DemoPage() {
  const [preset, setPreset] = useState<PresetId | null>(() => presetFrom(location.search));
  const initial = PRESETS[preset ?? 'answer'].body;
  const [answer, setAnswer] = useState(initial.response_text);
  const [question, setQuestion] = useState(initial.original_question ?? '');
  const [key, setKey] = useState(initial.answer_key?.text ?? '');
  const [useKey, setUseKey] = useState(Boolean(initial.answer_key));
  const { run, start } = useRunner();

  const choose = (id: PresetId) => {
    const body = PRESETS[id].body;
    setPreset(id);
    setAnswer(body.response_text);
    setQuestion(body.original_question ?? '');
    setKey(body.answer_key?.text ?? '');
    setUseKey(Boolean(body.answer_key));
    const url = new URL(location.href);
    url.searchParams.set('preset', id);
    history.replaceState(null, '', url);
  };
  const edited = preset !== null && (answer !== PRESETS[preset].body.response_text || key !== (PRESETS[preset].body.answer_key?.text ?? ''));
  const submit = () => {
    const body: DemoBody = { response_text: answer.trim(), original_question: question.trim() || undefined };
    if (useKey && key.trim()) body.answer_key = { name: 'Your policy', text: key.trim() };
    void start(body, edited ? null : preset);
  };
  const tooLong = answer.length > LIMITS.answer || question.length > LIMITS.question || key.length > LIMITS.key;
  const field = 'w-full rounded-xl border border-line-2 bg-black/30 px-4 py-3 text-[0.95rem] leading-relaxed text-ink outline-none transition-[border-color,box-shadow] focus:border-cyan/70 focus:shadow-[0_0_0_4px_rgb(56_214_255/0.12)]';

  return (
    <section className="relative overflow-hidden pb-24 pt-36">
      <Aurora blobs={[{ c: 'rgb(56 214 255 / 0.14)', x: '50%', y: '-20%' }, { c: 'rgb(139 92 255 / 0.12)', x: '-10%', y: '40%' }]} />
      <div className="grid-lines pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <Kicker>Live demo</Kicker>
        <h1 data-split className="t-display mt-7 max-w-[20ch]">Paste an AI answer. Watch every claim get checked.</h1>
        <p data-reveal className="mt-6 max-w-2xl text-lg text-ink-2">
          This runs the real TrustLayer engine in its quick mode. Pick an example or paste your own answer of up to 3,000 characters.
        </p>
        <div role="tablist" aria-label="Examples" className="glass mt-10 inline-flex max-w-full flex-wrap gap-1 rounded-full p-1">
          {(Object.keys(PRESETS) as PresetId[]).map(id => (
            <button key={id} type="button" role="tab" aria-selected={preset === id} onClick={() => choose(id)}
              className={`rounded-full px-4 py-2 text-sm transition-colors ${preset === id ? 'bg-ink text-bg shadow-[0_0_24px_-4px_rgb(255_255_255/0.6)]' : 'text-ink-2 hover:bg-white/5 hover:text-ink'}`}>
              {PRESETS[id].name}
            </button>
          ))}
        </div>
        <div className="mt-8 grid gap-6 lg:grid-cols-12">
          <div className="min-w-0 lg:col-span-5">
            <div className="glass beam rounded-[1.75rem] p-5 sm:p-7 lg:sticky lg:top-24">
              <label className="block">
                <span className="t-label flex justify-between text-muted"><span>Question (optional)</span><span>{question.length}/{LIMITS.question}</span></span>
                <input className={`${field} mt-2`} value={question} onChange={e => setQuestion(e.target.value)} maxLength={LIMITS.question} />
              </label>
              <label className="mt-5 block">
                <span className="t-label flex justify-between text-muted"><span>AI answer</span><span className={answer.length > LIMITS.answer ? 'text-bad' : ''}>{answer.length}/{LIMITS.answer}</span></span>
                <textarea className={`${field} mt-2 min-h-48 resize-y`} value={answer} onChange={e => setAnswer(e.target.value)} />
              </label>
              <label className="mt-5 flex items-center gap-3 text-sm text-ink-2">
                <input type="checkbox" className="h-4 w-4 accent-cyan" checked={useKey} onChange={e => setUseKey(e.target.checked)} />
                Check it only against my own policy (answer key)
              </label>
              {useKey && (
                <label className="mt-4 block">
                  <span className="t-label flex justify-between text-muted"><span>Your policy</span><span>{key.length}/{LIMITS.key}</span></span>
                  <textarea className={`${field} mt-2 min-h-32 resize-y font-mono text-sm`} value={key} onChange={e => setKey(e.target.value)} />
                </label>
              )}
              <button type="button" onClick={submit} disabled={!answer.trim() || tooLong || run.phase === 'running'} data-magnetic
                className="btn btn-primary mt-6 w-full justify-center disabled:cursor-not-allowed disabled:opacity-60">
                {run.phase === 'running' ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-bg border-t-transparent" /> Checking…</> : <>Check it <Arrow className="arrow h-4 w-4" /></>}
              </button>
              <p className="mt-4 text-xs leading-relaxed text-muted">
                Demo checks are never stored. Don't paste anything confidential: the text goes to our search and AI providers to be checked.
              </p>
            </div>
          </div>
          <div className="min-w-0 lg:col-span-7">
            {run.recordedAt && (
              <p role="status" className="mb-4 flex items-start gap-3 rounded-2xl border border-gold/40 bg-gold/10 px-4 py-3 text-sm text-ink">
                <Alert className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
                <span>{run.error}, so here's a recorded run of this example from {new Date(run.recordedAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}, replayed at speed.</span>
              </p>
            )}
            {run.phase === 'idle' && (
              <div className="glass spotlight grid min-h-[420px] place-items-center rounded-[1.75rem] p-10 text-center">
                <div>
                  <div className="mx-auto h-20 w-20 rounded-full border border-cyan/40 shadow-[0_0_60px_-10px_#38d6ff] [background:conic-gradient(from_0deg,transparent,rgb(56_214_255/0.5),transparent_40%)] motion-safe:animate-spin" style={{ animationDuration: '3s' }} />
                  <p className="mt-6 text-ink-2">Pick an example or paste an answer, then press <b className="text-ink">Check it</b>.</p>
                </div>
              </div>
            )}
            {run.phase === 'error' && (
              <div role="alert" className="glass rounded-[1.75rem] p-8">
                <p className="text-ink">{run.error?.replace(/\.$/, '')}. Pick one of the examples above to watch a recorded run, or ask us for a free check.</p>
                <div className="mt-6 flex flex-wrap gap-3"><Cta href="/report/sample/" size="sm">Read the sample report</Cta><Cta href="/check/?for=general" variant="ghost" size="sm">Get a free check</Cta></div>
              </div>
            )}
            {(run.phase === 'running' || run.phase === 'done') && (
              <div className="grid gap-4 xl:grid-cols-[15rem_minmax(0,1fr)]">
                <div className="glass h-fit min-w-0 rounded-2xl p-5 xl:sticky xl:top-24"><Timeline run={run} /></div>
                <div className="min-w-0">
                  {run.report ? <Results report={run.report} /> : (
                    <div className="glass rounded-2xl p-5">
                      <div className="t-label text-muted">Live feed</div>
                      <ul className="mt-4 space-y-1.5 font-mono text-xs text-ink-2">
                        {run.log.map(e => ({ e, line: plainStage(e.stage, e.status, e.message) })).filter(x => x.line).slice(-12)
                          .map(({ e, line }, i) => <li key={i}><span className="text-muted">{(e.elapsed_ms / 1000).toFixed(1)}s</span> {line}</li>)}
                        <li className="caret text-muted" />
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

mount(<Shell look={LOOK}><DemoPage /></Shell>);
