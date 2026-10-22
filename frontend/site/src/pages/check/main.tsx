import { useMemo, useRef, useState, type FormEvent } from 'react';
import type { Look } from '../../components/FieldCanvas';
import { mount, Shell } from '../../components/Shell';
import { Aurora, Cta, Kicker } from '../../fx/fx';
import { Arrow, Check } from '../../fx/icons';
import { audienceFrom, AUDIENCES, CONTACT_EMAIL, leadSource, leadSummary, sendLead, WOULD_PAY, type Audience, type LeadForm } from '../../lib/api';
import { gsap, reducedMotion, useGSAP } from '../../lib/motion';

const LOOK: Look = {
  desktop: { x: 3.9, y: 1.7, scale: 0.62, tilt: -0.35, opacity: 0.55, morph: 0, speed: 1 },
  mobile: { x: 0.6, y: 2.3, scale: 0.34, tilt: -0.3, opacity: 0.35, morph: 0, speed: 1 },
};

const TABS: Record<Audience, string> = {
  'product-teams': 'AI product team', documents: 'AI-written documents', 'support-bots': 'Support bot', general: 'Something else',
};

const COPY: Record<Audience, { title: string; sub: string; gets: string[]; placeholder: string; link: string }> = {
  'product-teams': {
    title: 'Get a free model-switch check',
    sub: 'Tell us which model you run now and which one you are moving to. We re-run your real questions on both and show you what broke.',
    gets: ['Up to 10 of your real questions, run on both models', 'Which answers broke, which changed, and why', 'The proof behind every finding'],
    placeholder: 'For example: our support assistant runs on GPT-4o and we have to move before 14 January 2027.',
    link: 'Link to your product',
  },
  documents: {
    title: 'Get a free document check',
    sub: 'Tell us about the AI-written document you want checked. We check every claim and citation and send you the proof.',
    gets: ['One document of up to about 10 pages', 'Every citation: does it exist, and does it say what you say', 'Wrong numbers and misquotes, with the source passage'],
    placeholder: 'For example: a 12-page client memo drafted with AI, with about 30 case citations.',
    link: 'Link to a public version',
  },
  'support-bots': {
    title: 'Get a free support-bot check',
    sub: 'Point us at your bot and your policy pages. We ask it real customer questions and check every answer against your own policy.',
    gets: ['10 real customer questions, asked by hand', 'Every answer checked against your own policy', 'Each wrong answer, the policy line it broke, and the corrected answer'],
    placeholder: 'For example: our website chatbot answers refund, delivery and loan-fee questions.',
    link: 'Link to your bot or help centre',
  },
  general: {
    title: 'Get a free check',
    sub: 'Tell us what your AI does and what worries you. We pick the right check and send you the findings, with proof.',
    gets: ['A check sized to what you send', 'Every wrong claim, with the source that proves it', 'A plain-language summary you can forward'],
    placeholder: 'For example: we use AI to answer customer questions about our loans.',
    link: 'Link',
  },
};

const STEPS = ['You tell us what to check', 'We run the check, by hand where it matters', 'You get every finding, with its proof'];

const EMPTY: Omit<LeadForm, 'audience'> = { name: '', email: '', company: '', role: '', message: '', link: '', consent: false, website: '', would_pay: '' };

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="t-label flex justify-between text-muted"><span>{label}</span>{hint && <span>{hint}</span>}</span>
      <span className="mt-2 block">{children}</span>
    </label>
  );
}

const input = 'w-full rounded-xl border border-line-2 bg-black/30 px-4 py-3 text-ink placeholder:text-muted outline-none transition-[border-color,box-shadow] focus:border-cyan/70 focus:shadow-[0_0_0_4px_rgb(56_214_255/0.12),0_0_30px_-6px_rgb(56_214_255/0.5)]';

function Success({ name, email }: { name: string; email: string }) {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (reducedMotion()) return;
    const q = gsap.utils.selector(root);
    gsap.timeline()
      .from(q('.ring'), { drawSVG: '0%', duration: 1, ease: 'power2.inOut' })
      .from(q('.tick'), { drawSVG: '0%', duration: 0.5 }, '-=0.3')
      .fromTo(q('.spark'), { x: 0, y: 0, scale: 1, opacity: 1 }, {
        x: (i: number) => Math.cos((i / 24) * Math.PI * 2) * (90 + (i % 3) * 40),
        y: (i: number) => Math.sin((i / 24) * Math.PI * 2) * (90 + (i % 3) * 40),
        scale: 0, opacity: 0, duration: 1.4, ease: 'expo.out', stagger: 0.01,
      }, '-=0.6')
      .from(q('.after'), { y: 20, opacity: 0, stagger: 0.1, duration: 0.9 }, '-=1.2');
  }, { scope: root });
  return (
    <div ref={root} role="status" className="flex flex-col items-center py-6 text-center">
      <div className="relative grid place-items-center">
        {Array.from({ length: 24 }, (_, i) => (
          <span key={i} aria-hidden="true" className="spark absolute h-1.5 w-1.5 rounded-full opacity-0" style={{ background: ['#38d6ff', '#8b5cff', '#ffc861'][i % 3] }} />
        ))}
        <svg width="96" height="96" viewBox="0 0 64 64" aria-hidden="true">
          <circle className="ring" cx="32" cy="32" r="26" fill="none" stroke="#38d6ff" strokeWidth="2.5" style={{ filter: 'drop-shadow(0 0 8px #38d6ff)' }} />
          <path className="tick" d="M21 33l7.5 7.5L44 25" fill="none" stroke="#f2f3f7" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <h2 className="after t-title mt-8">Thanks, {name.split(' ')[0]}. You're on the list.</h2>
      <p className="after mt-3 max-w-sm text-ink-2">We'll email <span className="text-ink">{email}</span> to set up your check.</p>
      <div className="after mt-8 flex flex-wrap justify-center gap-3">
        <Cta href="/demo/" size="sm">Try the live demo</Cta>
        <Cta href="/report/sample/" variant="ghost" size="sm">Read the sample report</Cta>
      </div>
    </div>
  );
}

/** The form could not be sent: never lose the lead. Offer a ready-made email and a copy button. */
function SendFailed({ message, summary, subject }: { message: string; summary: string; subject: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(summary); setCopied(true); } catch { setCopied(false); }
  };
  return (
    <div role="alert" className="space-y-3 rounded-xl border border-bad/50 bg-bad/10 px-4 py-3 text-sm text-ink">
      <p>{message}</p>
      <p className="text-ink-2">
        {CONTACT_EMAIL ? <>Or send it by email to{' '}
          <a className="font-medium text-ink underline" href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(summary)}`}>{CONTACT_EMAIL}</a>
          , with your details already filled in.</> : 'Your details are still in the form, so nothing is lost.'}
      </p>
      <button type="button" onClick={copy} className="rounded-full border border-line-2 px-3 py-1.5 text-xs text-ink hover:bg-white/5">
        {copied ? 'Copied' : 'Copy my details'}
      </button>
    </div>
  );
}

function CheckPage() {
  const [audience, setAudience] = useState<Audience>(() => audienceFrom(location.search));
  const [form, setForm] = useState(EMPTY);
  const [state, setState] = useState<'idle' | 'sending' | 'done'>('idle');
  const [error, setError] = useState('');
  // Where the visitor arrived, captured once: which button and campaign brought them here.
  const source = useMemo(() => leadSource(new URL(location.href), document.referrer), []);
  const copy = COPY[audience];
  const head = useRef<HTMLDivElement>(null);

  useGSAP(() => {
    if (reducedMotion()) return;
    gsap.from(head.current!.children, { y: 24, opacity: 0, filter: 'blur(8px)', stagger: 0.06, duration: 0.9 });
  }, { dependencies: [audience], scope: head });

  const choose = (next: Audience) => {
    setAudience(next);
    const url = new URL(location.href);
    url.searchParams.set('for', next);
    history.replaceState(null, '', url);
  };
  const set = <K extends keyof typeof EMPTY>(key: K) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [key]: key === 'consent' ? (e.target as HTMLInputElement).checked : e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setState('sending');
    const result = await sendLead({ ...form, audience }, source);
    if (result.ok) setState('done');
    else { setError(result.message); setState('idle'); }
  };

  return (
    <section className="relative overflow-hidden pb-24 pt-36">
      <Aurora blobs={[{ c: 'rgb(59 108 255 / 0.18)', x: '40%', y: '-20%' }, { c: 'rgb(139 92 255 / 0.12)', x: '-15%', y: '30%' }]} />
      <div className="grid-lines pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <div role="tablist" aria-label="Who is this check for?" className="glass inline-flex max-w-full flex-wrap gap-1 rounded-full p-1">
          {AUDIENCES.map(a => (
            <button key={a} role="tab" type="button" aria-selected={a === audience} onClick={() => choose(a)}
              className={`rounded-full px-4 py-2 text-sm transition-colors ${a === audience ? 'bg-ink text-bg shadow-[0_0_24px_-4px_rgb(255_255_255/0.6)]' : 'text-ink-2 hover:bg-white/5 hover:text-ink'}`}>
              {TABS[a]}
            </button>
          ))}
        </div>
        <div className="mt-12 grid gap-14 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <div ref={head}>
              <Kicker>Free check</Kicker>
              <h1 className="t-display mt-7">{copy.title}</h1>
              <p className="mt-6 text-lg text-ink-2">{copy.sub}</p>
            </div>
            <h2 className="t-label mt-12 text-muted">What you get</h2>
            <ul className="mt-5 space-y-3.5">
              {copy.gets.map(g => <li key={g} className="flex gap-3 text-ink"><Check className="mt-1 h-4 w-4 shrink-0 text-cyan" />{g}</li>)}
            </ul>
            <h2 className="t-label mt-12 text-muted">What happens next</h2>
            <ol className="relative mt-5 space-y-5 border-l border-line-2 pl-6">
              {STEPS.map(s => (
                <li key={s} className="relative text-ink-2">
                  <span className="absolute -left-[29px] top-1.5 h-2.5 w-2.5 rounded-full border border-cyan bg-bg shadow-[0_0_10px_#38d6ff]" />{s}
                </li>
              ))}
            </ol>
            <div className="glass mt-12 space-y-3 rounded-2xl p-5 text-sm text-ink-2">
              <p><b className="font-medium text-ink">Small on purpose.</b> The free check covers up to 10 questions or one short document. The full Bot Check-up, with 100 questions, 20 pushback tests and a written report, is a paid engagement.</p>
              <p><b className="font-medium text-ink">No confidential material here.</b> Don't paste private documents or customer data into this form. We'll agree a safe way to share anything sensitive.</p>
            </div>
          </div>
          <div className="lg:col-span-6 lg:col-start-7">
            <div className="glass beam rounded-[2rem] p-6 shadow-[0_40px_120px_-40px_rgb(56_214_255/0.35)] sm:p-9">
              {state === 'done' ? <Success name={form.name} email={form.email} /> : (
                <form onSubmit={submit} className="space-y-5" noValidate={false}>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field label="Your name"><input className={input} required maxLength={100} autoComplete="name" value={form.name} onChange={set('name')} /></Field>
                    <Field label="Work email"><input className={input} required type="email" maxLength={254} autoComplete="email" value={form.email} onChange={set('email')} /></Field>
                    <Field label="Company"><input className={input} maxLength={120} autoComplete="organization" value={form.company} onChange={set('company')} /></Field>
                    <Field label="Role"><input className={input} maxLength={80} autoComplete="organization-title" value={form.role} onChange={set('role')} /></Field>
                  </div>
                  <Field label="What should we check?" hint={`${form.message.length}/4000`}>
                    <textarea className={`${input} min-h-36 resize-y`} maxLength={4000} placeholder={copy.placeholder} value={form.message} onChange={set('message')} />
                  </Field>
                  <Field label={`${copy.link} (optional)`}>
                    <input className={input} type="url" maxLength={2048} placeholder="https://" value={form.link} onChange={set('link')} />
                  </Field>
                  <fieldset>
                    <legend className="t-label text-muted">Would you pay for a full check? (optional)</legend>
                    <p className="mt-2 text-sm text-ink-2">The full Bot Check-up: 100 questions, 20 pushback tests and a written report. What would it be worth to you?</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {WOULD_PAY.map(p => (
                        <label key={p.value} className={`rounded-full border px-4 py-2 text-sm transition-colors ${form.would_pay === p.value ? 'border-cyan bg-cyan/15 text-ink' : 'border-line-2 text-ink-2 hover:border-white/30'}`}>
                          <input type="radio" name="would_pay" value={p.value} checked={form.would_pay === p.value}
                            onChange={() => setForm(f => ({ ...f, would_pay: p.value }))} className="sr-only" />
                          {p.label}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
                    <label>Website<input tabIndex={-1} autoComplete="off" value={form.website} onChange={set('website')} /></label>
                  </div>
                  <label className="flex items-start gap-3 text-sm text-ink-2">
                    <input type="checkbox" required checked={form.consent} onChange={set('consent')}
                      className="mt-0.5 h-4 w-4 shrink-0 accent-cyan" />
                    <span>I agree that TrustLayer may keep these details and email me about this check. We also note which page or campaign link brought you here, and keep a one-way scrambled form of your IP address to stop spam.</span>
                  </label>
                  {error && <SendFailed message={error} summary={leadSummary({ ...form, audience }, TABS[audience])} subject={`Free check: ${TABS[audience]}`} />}
                  <button type="submit" disabled={state === 'sending'} data-magnetic
                    className="btn btn-primary w-full justify-center disabled:cursor-wait disabled:opacity-70">
                    {state === 'sending'
                      ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-bg border-t-transparent" /> Sending…</>
                      : <>Get my free check <Arrow className="arrow h-4 w-4" /></>}
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

mount(<Shell look={LOOK}><CheckPage /></Shell>);
