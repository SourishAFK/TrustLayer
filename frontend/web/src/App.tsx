import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowDown, ArrowDownToLine, ArrowRight, ArrowUpRight, Braces, Check, ChevronDown, CircleDashed, Clock3, FileText, Fingerprint, Layers3, LoaderCircle, LockKeyhole, ScanLine, Search, ShieldCheck, Sparkles, X, Zap } from 'lucide-react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';
import 'lenis/dist/lenis.css';
import SpotlightCard from './SpotlightCard';
import { downloadReport, highlightParts, parseReport, type Claim, type Report } from './report';

gsap.registerPlugin(ScrollTrigger);
const EXAMPLE = 'Acme is an AI research copilot for competitive-intelligence teams. It has no competitors, and generates $50 billion annually.\n\nThe market grew from $20 million to $30 million, an increase of 80%. Our product will capture half the market next year.\n\nI think this is a brilliant startup idea.';
const LABELS: Record<string, string> = { business_market: 'Business & market', negative_universal: 'Negative / universal', subjective_normative: 'Subjective / normative', not_independently_checkable: 'Not independently checkable', time_sensitive: 'Time-sensitive' };
const label = (kind: string) => LABELS[kind] || kind.replaceAll('_', ' ');

function Orbital() {
  return <div className="orbital" aria-hidden="true">
    <div className="orbital-grid" />
    <svg className="orbital-rings" viewBox="0 0 400 260"><defs>
      <linearGradient id="orbit-gradient"><stop stopColor="#c9b9ff" /><stop offset=".5" stopColor="#6f54fa" /><stop offset="1" stopColor="#64d9d0" /></linearGradient>
      <radialGradient id="orb-glow"><stop stopColor="#9a7dff" stopOpacity=".4" /><stop offset="1" stopColor="#7161da" stopOpacity="0" /></radialGradient>
    </defs><ellipse cx="200" cy="130" rx="115" ry="110" fill="url(#orb-glow)" />
      <g fill="none" stroke="url(#orbit-gradient)"><ellipse cx="200" cy="130" rx="123" ry="60" transform="rotate(-30 200 130)" /><ellipse cx="200" cy="130" rx="123" ry="60" transform="rotate(30 200 130)" /><ellipse cx="200" cy="130" rx="60" ry="107" /></g>
      <g fill="#cabfff"><circle cx="103" cy="80" r="3" /><circle cx="292" cy="183" r="3" /><circle cx="223" cy="28" r="3" /></g>
    </svg>
    <div className="orbital-core"><ScanLine size={30} strokeWidth={1.2} /></div>
    <span className="orbital-tag tag-top"><span /> CLAIM EXTRACTION</span>
    <span className="orbital-tag tag-bottom">EVIDENCE COMES NEXT <ArrowUpRight size={12} /></span>
  </div>;
}

function ClaimDetail({ claim }: { claim: Claim }) {
  return <div className="claim-detail" key={claim.claim_id}>
    <div className="detail-heading"><span className="eyebrow">INSPECTING {claim.claim_id.toUpperCase()}</span><span className={`status ${claim.objectively_checkable ? 'unverified' : 'neutral'}`}>{claim.verification_status}</span></div>
    <blockquote>{claim.exact_text}</blockquote><p>{claim.explanation}</p>
    <div className="detail-facts"><div><span>Claim type</span><strong>{label(claim.claim_type)}</strong></div><div><span>Dates identified</span><strong>{claim.scope.dates.join(', ') || 'None identified'}</strong></div><div><span>Geographic scope</span><strong>{claim.scope.geographical_scope.join(', ') || 'None identified'}</strong></div><div><span>Qualifiers</span><strong>{claim.qualifiers.join(', ') || 'None identified'}</strong></div></div>
    <div className="evidence-empty"><Search size={17} /><div><strong>No evidence retrieved</strong><p>Supporting and contradictory sources have not been investigated. No correction is suggested.</p></div></div>
    <details><summary>Original context & extraction notes <ChevronDown size={14} /></summary><p>{claim.context}</p><p className="mono">Characters {claim.text_span.start}–{claim.text_span.end} · Unicode code points</p>{claim.limitations.map((note, i) => <p key={i} className="warning-note">{note}</p>)}</details>
  </div>;
}

export default function App() {
  const page = useRef<HTMLDivElement>(null);
  const reportHeading = useRef<HTMLHeadingElement>(null);
  const controller = useRef<AbortController | null>(null);
  const [response, setResponse] = useState('');
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<'quick' | 'deep'>('quick');
  const [key, setKey] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [inputView, setInputView] = useState<'edit' | 'claims'>('edit');
  const [filter, setFilter] = useState('all');
  const [motion, setMotion] = useState(true);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!motion) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const lenis = new Lenis({ autoRaf: false, duration: 1.05, anchors: true,
        prevent: node => node.tagName === 'TEXTAREA' || node.hasAttribute('data-lenis-prevent') });
      const tick = (time: number) => lenis.raf(time * 1000);
      gsap.ticker.add(tick); lenis.on('scroll', ScrollTrigger.update);
      const context = gsap.context(() => {
        gsap.from('.entrance', { y: 22, opacity: 0, duration: .85, stagger: .1, ease: 'power3.out', clearProps: 'all' });
        gsap.to('.orbital-rings', { rotation: 8, y: -7, duration: 5, repeat: -1, yoyo: true, ease: 'sine.inOut' });
        gsap.from('.principle', { y: 28, opacity: 0, stagger: .12, duration: .8, scrollTrigger: { trigger: '.principles', start: 'top 92%', once: true } });
      }, page);
      return () => { context.revert(); gsap.ticker.remove(tick); lenis.destroy(); };
    });
    return () => media.revert();
  }, [motion]);

  useEffect(() => {
    if (!report) return;
    reportHeading.current?.focus({ preventScroll: true });
    if (motion && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const ctx = gsap.context(() => gsap.from('.claim-row', { opacity: 0, y: 8, duration: .35, stagger: .025, clearProps: 'all' }), page);
      return () => ctx.revert();
    }
  }, [report, motion]);

  const selected = report?.claims.find(c => c.claim_id === selectedId);
  const stale = !!report && (report.response_text !== response || report.original_question !== (question.trim() || null) || report.mode !== mode);
  const visibleClaims = report?.claims.filter(c => filter === 'all' || (filter === 'checkable' ? c.objectively_checkable : !c.objectively_checkable)) || [];

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!response.trim()) { setError('Paste an AI response to identify its claims.'); return; }
    if (Array.from(response).length > 24000 || Array.from(question).length > 8000) { setError('Input exceeds the character limit. Shorten the text and try again.'); return; }
    if (!key.trim().startsWith('tl_')) { setError('Open API access and enter your TrustLayer key (tl_…). Provider keys are not accepted.'); return; }
    setError(''); setReport(null); setSelectedId(''); setBusy(true);
    const abort = new AbortController(); controller.current = abort;
    const timer = setTimeout(() => abort.abort(), 20000);
    try {
      const result = await fetch('/v1/claims/extract', { method: 'POST', signal: abort.signal,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key.trim()}` },
        body: JSON.stringify({ response_text: response, original_question: question.trim() || null, mode }) });
      if (!result.ok) {
        const messages: Record<number, string> = { 401: 'Your TrustLayer key was not accepted. Update API access and try again.', 422: 'The API could not accept this input. Check the character limits.', 429: 'Your daily request limit has been reached. Try again after it resets.', 503: 'The authentication, quota or extraction service is unavailable. No verification was completed.' };
        throw new Error(messages[result.status] || 'The API could not complete extraction. Please try again.');
      }
      let parsed: Report;
      try { parsed = parseReport(await result.json(), response); }
      catch { throw new Error('The API returned an invalid report. It has not been presented as a successful check.'); }
      if (parsed.extraction_status === 'failed') throw new Error('Extraction failed safely. No claims or positive verdicts were produced.');
      setReport(parsed); setSelectedId(parsed.claims[0]?.claim_id || ''); setInputView('claims'); setFilter('all');
    } catch (cause) {
      setError(abort.signal.aborted ? 'The request was cancelled or timed out. No report was completed.' : cause instanceof Error ? cause.message : 'Could not reach the API. Check that the backend is running.');
    } finally { clearTimeout(timer); controller.current = null; setBusy(false); }
  }

  function loadExample() {
    setResponse(EXAMPLE); setQuestion('Evaluate this startup research report and its market assumptions.');
    setInputView('edit'); setError('');
  }

  return <div ref={page} className={!motion ? 'motion-off' : ''}>
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar"><a className="brand" href="#"><span className="brand-mark"><Layers3 size={22} /></span>TrustLayer<span className="version">2.0</span></a>
      <nav aria-label="Main navigation"><a className="nav-active" href="#workspace">Workbench</a><a href="#methodology">Methodology</a><a href="/docs">API <ArrowUpRight size={12} /></a></nav>
      <details className="connection"><summary><span className={`connection-dot ${key ? 'configured' : ''}`} />API access <ChevronDown size={13} /></summary><div className="connection-panel"><label htmlFor="access-key">TrustLayer API key</label><input id="access-key" type="password" autoComplete="off" spellCheck={false} value={key} onChange={e => setKey(e.target.value)} placeholder="tl_…" /><p>A caller-owned TrustLayer key. Kept in memory, sent to this API only. Never enter a model-provider key.</p><button type="button" className="text-button" onClick={() => setKey('')}>Clear key</button></div></details>
    </header>

    <main>
      <section className="hero">
        <div className="hero-copy"><div className="eyebrow entrance"><span className="live-dot" /> THE RESPONSE VERIFICATION WORKSPACE</div>
          <h1 className="entrance">Every answer.<br /><span>Open to scrutiny.</span></h1>
          <p className="hero-description entrance">Good answers should stand up to a closer look.<br className="desktop-break" /> Start with the claims. Keep the uncertainty in view.</p>
          <div className="hero-meta entrance"><span><LockKeyhole size={13} /> No third-party model calls</span><i /><span>LEVEL 01 <span className="subtle">/ Claim extraction</span></span></div>
        </div><div className="entrance hero-art"><Orbital /></div>
      </section>

      <div className="workspace-heading entrance" id="workspace"><div><span className="section-number">01 /</span><h2>Response workbench</h2></div><span className="stage-badge"><CircleDashed size={12} /> Extraction preview</span></div>
      <div className="scope-notice entrance"><Fingerprint size={17} /><p><strong>Clarity starts with knowing the limits.</strong> This release identifies claims. Evidence research and factual verification have not run.</p><a href="#methodology" aria-label="Read extraction methodology"><ArrowDown size={16} /></a></div>

      <form onSubmit={verify}>
        <div className="workspace-grid entrance">
          <section className="input-panel panel" aria-labelledby="input-heading">
            <div className="panel-heading"><div><FileText size={16} /><h3 id="input-heading">The original response</h3></div><button type="button" className="text-button" onClick={loadExample} disabled={busy}><Sparkles size={13} /> Load startup example</button></div>
            <div className="input-tabs"><button className={inputView === 'edit' ? 'active' : ''} type="button" onClick={() => setInputView('edit')}>Compose</button><button className={inputView === 'claims' ? 'active' : ''} type="button" disabled={!report} onClick={() => setInputView('claims')}>Claim highlights {report && <span>{report.claims.length}</span>}</button><span className="input-origin">ANY MODEL. ANY RESPONSE.</span></div>
            {inputView === 'edit' || !report ? <><label className="sr-only" htmlFor="response">AI response</label><textarea id="response" data-lenis-prevent value={response} onChange={e => setResponse(e.target.value)} disabled={busy} placeholder={'Paste an AI-generated response here…\n\nA market report. A confident recommendation. A conclusion you want to examine.\n\nWe’ll separate it into claims you can inspect.'} /><div className="input-foot"><span><LockKeyhole size={11} /> Text is not stored by extraction</span><span className={Array.from(response).length > 24000 ? 'error-text' : ''}>{Array.from(response).length.toLocaleString()} / 24,000</span></div></> : <div className="highlighted-text" data-lenis-prevent aria-label="Response with highlighted claims">{highlightParts(report.response_text, report.claims).map((part, i) => part.claim ? <button type="button" key={i} className={`claim-highlight ${selectedId === part.claim.claim_id ? 'selected' : ''}`} onClick={() => setSelectedId(part.claim!.claim_id)} aria-pressed={selectedId === part.claim.claim_id} aria-label={`Inspect ${part.claim.claim_id}: ${part.text}`}>{part.text}<sup>{part.claim.claim_id.slice(1)}</sup></button> : <span key={i}>{part.text}</span>)}</div>}
            <div className="question-field"><label htmlFor="question">Original question <span>Optional · adds context</span></label><input id="question" value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} placeholder="What did you ask the AI?" /></div>
            <div className="mode-section"><span className="field-label">Investigation mode</span><div className="mode-options" role="radiogroup" aria-label="Investigation mode"><label className={mode === 'quick' ? 'mode selected' : 'mode'}><input type="radio" name="mode" value="quick" checked={mode === 'quick'} onChange={() => setMode('quick')} disabled={busy} /><Zap size={16} /><span><strong>Quick Check</strong><small>Start with the claims</small></span><span className="radio-dot" /></label><label className={mode === 'deep' ? 'mode selected' : 'mode'}><input type="radio" name="mode" value="deep" checked={mode === 'deep'} onChange={() => setMode('deep')} disabled={busy} /><Search size={16} /><span><strong>Deep Investigation</strong><small>Extraction only for now</small></span><span className="radio-dot" /></label></div><p className="mode-note">{mode === 'deep' ? 'Deep research is not available yet. This runs the same extraction baseline as Quick Check.' : 'Level 1 runs claim extraction only. Numerical, source and sycophancy checks are pending.'}</p></div>
            <div className="submit-area"><button type="submit" className="primary-button" disabled={busy}>{busy ? <><LoaderCircle size={16} className="spin" /> Extracting claims…</> : <><ScanLine size={17} /> Verify Response <ArrowRight size={17} /></>}</button>{busy ? <button className="text-button" type="button" onClick={() => controller.current?.abort()}>Cancel request</button> : <span>Local extraction <span>·</span> $0 model & search cost</span>}</div>
          </section>

          <SpotlightCard className="report-panel panel"><section aria-labelledby="report-heading" aria-busy={busy}>
            <div className="panel-heading"><div><ScanLine size={17} /><h3 id="report-heading" ref={reportHeading} tabIndex={-1}>The verification report</h3></div><span className="report-counter">{report ? `${String(report.claims.length).padStart(2, '0')} CLAIMS` : 'AWAITING INPUT'}</span></div>
            <div className="pipeline"><span className={report || busy ? 'current' : ''}><span>{report ? <Check size={10} /> : '1'}</span> Extract</span><i /><span><span>2</span> Investigate <small>Later</small></span><i /><span><span>3</span> Evidence <small>Later</small></span></div>
            {busy ? <div className="empty-state loading-state" role="status"><div className="scan-symbol"><ScanLine size={37} /></div><h4>Making the claims visible.</h4><p>Parsing your response and validating exact text spans.</p><div className="loading-track" /><span className="eyebrow">EXTRACTION ONLY · NO WEB RESEARCH</span></div> : report ? <>
              {stale && <div className="stale-note" role="status">Inputs changed. This report describes the previous submission. Run again to update it.</div>}
              <div className="report-summary"><span className="eyebrow">EXTRACTION {report.extraction_status === 'partial' ? 'PARTIAL' : 'FINISHED'}</span><h4>{report.claims.length} statements.<br /><span>None investigated yet.</span></h4><p>These counts describe extracted claims, not guaranteed coverage.</p></div>
              <div className="stat-grid">{[['Supported', 0, 'support'], ['Contradicted', 0, 'contradict'], ['Disputed', 0, 'disputed'], ['Unverified', report.summary.unverified, 'unverified'], ['Not checkable', report.summary.not_checkable, 'neutral'], ['Investigated', 0, 'neutral']].map(([name, count, color]) => <div key={String(name)}><strong>{count}</strong><span><i className={String(color)} />{name}</span></div>)}</div>
              <div className="claim-list-heading"><strong>Claim inventory</strong><label className="sr-only" htmlFor="claim-filter">Filter claims</label><select id="claim-filter" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All statements</option><option value="checkable">Checkable</option><option value="other">Not checkable</option></select></div>
              <div className="claim-list" data-lenis-prevent>{visibleClaims.length ? visibleClaims.map(claim => <button type="button" className={`claim-row ${selectedId === claim.claim_id ? 'selected' : ''}`} onClick={() => setSelectedId(claim.claim_id)} aria-pressed={selectedId === claim.claim_id} key={claim.claim_id}><span className="claim-number">{claim.claim_id.slice(1).padStart(2, '0')}</span><span><strong>{claim.exact_text}</strong><small>{label(claim.claim_type)} <i /> {claim.verification_status}</small></span><ArrowUpRight size={15} /></button>) : <p className="no-claims">No statements in this view. Extraction can miss claims; review the original text.</p>}</div>
              {selected && <ClaimDetail claim={selected} />}
              <details className="checks-details" open><summary><CircleDashed size={15} /> What remains unchecked <ChevronDown size={14} /></summary><ul>{report.incomplete_checks.map((check, i) => <li key={i}>{check}</li>)}</ul></details>
              <details className="checks-details"><summary>Extraction limitations <ChevronDown size={14} /></summary><ul>{report.limitations.map((item, i) => <li key={i}>{item}</li>)}{report.omitted_segments.map((item, i) => <li key={`o${i}`}>Omitted {item.text_span.start}–{item.text_span.end}: {item.reason}</li>)}</ul></details>
              <div className="export-bar"><span><Clock3 size={12} /> {report.usage.duration_ms.toFixed(1)} ms</span><button type="button" onClick={() => downloadReport(report, 'json')}><Braces size={14} /> JSON</button><button type="button" onClick={() => downloadReport(report, 'txt')}><ArrowDownToLine size={14} /> Readable report</button></div>
            </> : <div className="empty-state"><div className="empty-diagram" aria-hidden="true"><div className="empty-ring" /><div className="scan-symbol"><ScanLine size={34} strokeWidth={1.3} /></div><span className="diagram-point p1" /><span className="diagram-point p2" /><span className="diagram-point p3" /></div><span className="eyebrow">A SECOND LOOK STARTS HERE</span><h4>What’s behind<br />the answer?</h4><p>Add a response to reveal its individual claims,<br />their context, and what still needs checking.</p><div className="empty-capabilities"><span><Fingerprint size={14} /> Exact text spans</span><span><Layers3 size={14} /> Claim categories</span><span><CircleDashed size={14} /> Explicit uncertainty</span></div><div className="empty-foot"><ShieldCheck size={15} /><span>No verdict without an investigation.</span></div></div>}
          </section></SpotlightCard>
        </div>
        {error && <div className="error-banner" role="alert"><span>{error}</span><button type="button" aria-label="Dismiss error" onClick={() => setError('')}><X size={17} /></button></div>}
      </form>

      <section className="methodology" id="methodology"><div className="method-heading"><div><span className="eyebrow">THE PRINCIPLE BEHIND THE PRODUCT</span><h2>Trust needs a paper trail.</h2></div><p>We’re building toward independently checkable answers.<br />This is the first step, with its limits in plain sight.</p></div><div className="principles">
        <article className="principle"><span className="principle-number">01</span><Fingerprint size={21} /><h3>Preserve the claim.</h3><p>Exact words, original context, visible qualifiers. Inspect what the response actually says.</p><span className="available"><Check size={11} /> Available in this release</span></article>
        <article className="principle"><span className="principle-number">02</span><Search size={21} /><h3>Follow the evidence.</h3><p>Independent sources and their disagreements will inform verdicts. Model confidence is not evidence.</p><span className="planned">Next · Evidence investigation</span></article>
        <article className="principle"><span className="principle-number">03</span><CircleDashed size={21} /><h3>Make uncertainty visible.</h3><p>Unverified means unverified. No universal truth score. No quiet leap from an assertion to a fact.</p><span className="available"><Check size={11} /> Available in this release</span></article>
      </div></section>
      <footer><a className="brand footer-brand" href="#"><Layers3 size={19} />TrustLayer</a><span>Confidence is not trust.</span><div><button type="button" className="text-button" aria-pressed={!motion} onClick={() => setMotion(!motion)}>Motion {motion ? 'on' : 'off'}</button><a href="/docs">Developer API <ArrowUpRight size={12} /></a></div></footer>
    </main>
  </div>;
}
