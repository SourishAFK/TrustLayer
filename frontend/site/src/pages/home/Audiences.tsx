import { useRef, type ReactNode } from 'react';
import { Aurora, Cite, Counter, Cta, Kicker, Scramble, VerdictChip } from '../../fx/fx';
import { Check, Cross } from '../../fx/icons';
import type { SourceKey } from '../../lib/content';
import { gsap, scrollStory, SplitText, useGSAP } from '../../lib/motion';

type Tone = 'cyan' | 'gold' | 'violet';
type Stat = { value: ReactNode; caption: ReactNode; cite: SourceKey[] };

const TONE: Record<Tone, { beam: string; glow: string; blobs: { c: string; x: string; y: string }[] }> = {
  cyan: { beam: '', glow: 'glow-cyan', blobs: [{ c: 'rgb(56 214 255 / 0.13)', x: '50%', y: '10%' }, { c: 'rgb(59 108 255 / 0.12)', x: '-10%', y: '50%' }] },
  gold: { beam: 'beam-gold', glow: 'glow-gold', blobs: [{ c: 'rgb(255 200 97 / 0.10)', x: '-5%', y: '15%' }, { c: 'rgb(255 90 54 / 0.08)', x: '55%', y: '55%' }] },
  violet: { beam: 'beam-violet', glow: 'glow-violet', blobs: [{ c: 'rgb(139 92 255 / 0.15)', x: '50%', y: '5%' }, { c: 'rgb(255 90 209 / 0.07)', x: '-10%', y: '55%' }] },
};

function AudienceSection({ id, tone, kicker, pitch, body, stats, audience, visual }: {
  id: string; tone: Tone; kicker: string; pitch: string; body: ReactNode; stats: Stat[];
  audience: string; visual: ReactNode;
}) {
  return (
    <section id={id} className="relative py-28 lg:min-h-[200vh] lg:py-0">
      <Aurora blobs={TONE[tone].blobs} />
      <div className="relative z-10 mx-auto max-w-7xl px-6 lg:grid lg:grid-cols-12 lg:gap-16">
        <div className="lg:col-span-5 lg:py-[22vh]">
          <Kicker tone={tone === 'gold' ? 'gold' : tone}>{kicker}</Kicker>
          <h2 data-split className="t-display mt-7">{pitch}</h2>
          <div data-reveal className="mt-8 space-y-4 text-lg text-ink-2">{body}</div>
          <dl className="mt-12 grid gap-9">
            {stats.map((s, i) => (
              <div key={i} data-reveal className="border-l border-line-2 pl-5">
                <dt className="text-[clamp(2.4rem,4.4vw,3.6rem)] font-semibold leading-none tracking-[-0.04em] text-ink">{s.value}</dt>
                <dd className="mt-3 max-w-md text-[0.95rem] text-ink-2">{s.caption}{s.cite.map(k => <Cite key={k} k={k} />)}</dd>
              </div>
            ))}
          </dl>
          <div data-reveal className="mt-12">
            <Cta href={`/check/?for=${audience}`} cursor="Free">Get a free check</Cta>
          </div>
        </div>
        <div className="mt-16 lg:col-span-7 lg:mt-0">
          <div className="lg:sticky lg:top-[13vh] lg:py-[2vh]">{visual}</div>
        </div>
      </div>
    </section>
  );
}

function Illustration({ children }: { children: ReactNode }) {
  return <p className="t-label mt-4 text-right text-muted/80">{children}</p>;
}

/* ---------------- AI product teams: a model switch, re-checked ---------------- */

const SWITCH_ROWS = [
  { q: "What's the late-payment fee?", after: 'same' },
  { q: 'Can I pause my subscription?', after: 'same' },
  { q: 'Do you ship to Canada?', after: 'changed', note: 'Reworded, still correct' },
  { q: "What's the refund window?", after: 'broke', note: 'Now says 60 days. Your policy: 30' },
  { q: 'Which plan includes single sign-on?', after: 'same' },
  { q: 'Is my data used to train models?', after: 'broke', note: 'Now says "never". Your policy: only with opt-in' },
] as const;

function ModelSwitch() {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = root.current!;
    const q = gsap.utils.selector(el);
    // Start states are set outright: a paused timeline never renders its own opening .set() calls.
    gsap.set(q('.after-result'), { autoAlpha: 0 });
    gsap.set(q('.after-pending'), { autoAlpha: 1 });
    gsap.set(q('.summary > *'), { autoAlpha: 0, y: 16 });
    scrollStory(el.closest('section')!, el, () => {
      const tl = gsap.timeline({ defaults: { ease: 'power2.out' } });
      tl.to(q('.model'), { duration: 1.2, ease: 'none', scrambleText: { text: 'replacement model', chars: 'lowerCase', speed: 0.5 } })
        .fromTo(q('.scan'), { top: '0%', autoAlpha: 0 }, { autoAlpha: 1, duration: 0.2 })
        .to(q('.scan'), { top: '100%', duration: SWITCH_ROWS.length * 0.7, ease: 'none' });
      q('.row').forEach((row, i) => {
        const at = 1.5 + i * 0.7;
        tl.to(row.querySelector('.after-pending'), { autoAlpha: 0, duration: 0.15 }, at)
          .fromTo(row.querySelector('.after-result'), { autoAlpha: 0, x: 10 }, { autoAlpha: 1, x: 0, duration: 0.4 }, at);
        if (row.dataset.after === 'broke') {
          tl.to(row, { backgroundColor: 'rgb(212 49 38 / 0.14)', boxShadow: 'inset 3px 0 0 #d43126', duration: 0.3 }, at)
            .fromTo(row, { x: -8 }, { x: 0, duration: 0.6, ease: 'elastic.out(1, 0.3)' }, at);
        }
      });
      return tl.to(q('.scan'), { autoAlpha: 0, duration: 0.3 })
        .to(q('.summary > *'), { autoAlpha: 1, y: 0, stagger: 0.15, duration: 0.5 });
    });
  }, { scope: root });

  return (
    <div ref={root}>
      <div className={`glass beam ${TONE.cyan.glow} rounded-3xl p-5 sm:p-7`} data-tilt>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="t-label text-ink-2">Re-check after a model switch</span>
          <span className="flex items-center gap-2 font-mono text-xs">
            <span className="rounded-md border border-line-2 px-2 py-1 text-muted">current model</span>
            <span className="text-muted">→</span>
            <span className="model rounded-md border border-cyan/40 bg-cyan/10 px-2 py-1 text-ink">current model</span>
          </span>
        </div>
        <div className="relative mt-6 overflow-hidden rounded-2xl border border-line">
          <div className="grid grid-cols-[1fr_minmax(7.5rem,46%)] gap-4 border-b border-line bg-white/[0.02] px-4 py-2.5 t-label text-muted sm:grid-cols-[1fr_auto_minmax(8rem,38%)]">
            <span>Question</span><span className="hidden sm:block">Before</span><span>After</span>
          </div>
          {SWITCH_ROWS.map(r => (
            <div key={r.q} data-after={r.after} className="row grid grid-cols-[1fr_minmax(7.5rem,46%)] items-center gap-4 border-b border-line px-4 py-3 last:border-0 sm:grid-cols-[1fr_auto_minmax(8rem,38%)]">
              <span className="text-[0.92rem] text-ink">{r.q}</span>
              <Check className="hidden h-4 w-4 text-ok sm:block" aria-label="Correct" />
              <span className="relative grid">
                <span className="after-pending col-start-1 row-start-1 font-mono text-xs text-muted">waiting…</span>
                <span className="after-result col-start-1 row-start-1 flex items-start gap-2 text-[0.82rem] leading-snug">
                  {r.after === 'broke' ? <Cross className="mt-0.5 h-4 w-4 shrink-0 text-bad" /> : <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" />}
                  <span className={r.after === 'broke' ? 'text-ink' : 'text-ink-2'}>
                    {r.after === 'same' ? 'Same answer' : r.note}
                  </span>
                </span>
              </span>
            </div>
          ))}
          <div className="scan pointer-events-none absolute inset-x-0 h-12 -translate-y-1/2 bg-[linear-gradient(180deg,transparent,rgb(56_214_255/0.16),transparent)] opacity-0">
            <div className="absolute inset-x-0 top-1/2 h-px bg-cyan shadow-[0_0_16px_#38d6ff]" />
          </div>
        </div>
        <div className="summary mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
          <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-bad shadow-[0_0_10px_#d43126]" /><b className="font-semibold text-ink">2 broke</b></span>
          <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-warn" /><b className="font-semibold text-ink">1 changed</b></span>
          <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-ok" /><b className="font-semibold text-ink">3 the same</b></span>
          <span className="ml-auto font-mono text-xs text-ink-2">Found before your users did.</span>
        </div>
      </div>
      <Illustration>Illustration · invented example</Illustration>
    </div>
  );
}

/* ---------------- AI-written documents: every claim and citation ---------------- */

function DocumentCheck() {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = root.current!;
    const q = gsap.utils.selector(el);
    gsap.set(q('.verdict'), { autoAlpha: 0 });
    scrollStory(el.closest('section')!, el, () => gsap.timeline()
      .fromTo(q('.mark'), { backgroundSize: '0% 100%' }, { backgroundSize: '100% 100%', stagger: 0.8, duration: 0.7, ease: 'none' })
      .fromTo(q('.ring'), { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 0.8 }, 0.8)
      .to(q('.v-number'), { autoAlpha: 1, duration: 0.4 }, 1.3)
      .fromTo(q('.strike'), { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 0.6 }, 2.0)
      .fromTo(q('.stamp'), { autoAlpha: 0, scale: 1.8, rotate: -18 }, { autoAlpha: 1, scale: 1, rotate: -8, duration: 0.5, ease: 'back.out(1.6)' }, 2.4)
      .to(q('.v-case'), { autoAlpha: 1, duration: 0.4 }, 2.5)
      .to(q('.v-ok'), { autoAlpha: 1, duration: 0.4 }, 3.1)
      .from(q('.doc-summary'), { autoAlpha: 0, y: 14, duration: 0.5 }, 3.5));
  }, { scope: root });

  const mark = 'mark rounded-sm bg-no-repeat px-0.5 [background-image:linear-gradient(rgb(255_200_97/0.22),rgb(255_200_97/0.22))]';
  return (
    <div ref={root}>
      <div className={`glass beam ${TONE.gold.beam} ${TONE.gold.glow} relative rounded-3xl p-6 sm:p-8`} data-tilt>
        <div className="flex items-center justify-between">
          <span className="t-label text-ink-2">Market entry review · draft 3</span>
          <span className="t-label text-muted">Checked: 3 claims · 3 citations</span>
        </div>
        <div className="mt-6 space-y-5 font-serif text-[1.18rem] leading-relaxed text-ink">
          <p>
            Mid-sized lenders grew digital loan volumes by{' '}
            <span className="relative inline-block">
              <span className={mark}>47%</span>
              <svg className="pointer-events-none absolute -inset-x-3 -inset-y-2 h-[calc(100%+16px)] w-[calc(100%+24px)] overflow-visible" viewBox="0 0 100 50" preserveAspectRatio="none" aria-hidden="true">
                <path className="ring" d="M50 3 C 85 2, 98 18, 95 30 C 92 45, 30 49, 10 40 C -4 31, 6 8, 40 4" fill="none" stroke="#ff5a36" strokeWidth="2.5" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength={1} strokeDasharray="1" />
              </svg>
            </span>{' '}
            in 2024.<sup className="font-mono text-xs text-gold">[1]</sup>
          </p>
          <p>
            As the court held in <span className={mark}>Varga v. Ostrander Holdings (2019)</span>, automated advice
            “carries the same duty of care as a human adviser”.<sup className="font-mono text-xs text-gold">[2]</sup>
          </p>
          <p>
            Lenders are expected to <span className={mark}>show the full yearly cost of a loan before the customer signs</span>.
            <sup className="font-mono text-xs text-gold">[3]</sup>
          </p>
        </div>
        <ol className="mt-7 space-y-3 border-t border-line pt-5 text-sm">
          <li className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1.5 sm:grid-cols-[auto_1fr_auto]">
            <span className="font-mono text-gold">[1]</span><span className="text-ink-2">Industry lending survey 2025, p. 14</span>
            <span className="verdict v-number col-start-2 sm:col-start-3"><VerdictChip verdict="CONTRADICTED" label="Source says 37%" /></span>
          </li>
          <li className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1.5 sm:grid-cols-[auto_1fr_auto]">
            <span className="font-mono text-gold">[2]</span>
            <span className="relative w-fit text-ink-2">
              Varga v. Ostrander Holdings (2019)
              <svg className="pointer-events-none absolute left-0 top-1/2 h-2 w-full -translate-y-1/2 overflow-visible" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">
                <path className="strike" d="M0 2.5 L 100 1.5" stroke="#ff5a36" strokeWidth="2" vectorEffect="non-scaling-stroke" pathLength={1} strokeDasharray="1" />
              </svg>
            </span>
            <span className="verdict v-case col-start-2 sm:col-start-3"><VerdictChip verdict="CONTRADICTED" label="No such case found" /></span>
          </li>
          <li className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1.5 sm:grid-cols-[auto_1fr_auto]">
            <span className="font-mono text-gold">[3]</span><span className="text-ink-2">Regulator's guidance on loan disclosures</span>
            <span className="verdict v-ok col-start-2 sm:col-start-3"><VerdictChip verdict="SUPPORTED" label="Says exactly this" /></span>
          </li>
        </ol>
        <div className="stamp pointer-events-none absolute bottom-16 right-6 rounded-lg border-2 border-ember px-3 py-1.5 font-mono text-sm font-bold tracking-[0.2em] text-ember opacity-0 shadow-[0_0_30px_rgb(255_90_54/0.35)] sm:right-10">
          CASE NOT FOUND
        </div>
        <p className="doc-summary mt-6 font-mono text-xs text-ink-2">1 wrong number · 1 citation that doesn't exist · 1 confirmed — each with the passage that proves it.</p>
      </div>
      <Illustration>Illustration · invented names and sources</Illustration>
    </div>
  );
}

/* ---------------- Customer-support bots: checked against your own policy ---------------- */

function SupportBot() {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = root.current!;
    const q = gsap.utils.selector(el);
    // A curve from the bot's wrong number to the policy line it contradicts (desktop layout only).
    const stage = q('.stage')[0], link = q('.link')[0];
    const draw = () => {
      const box = stage.getBoundingClientRect(), a = q('.wrong')[0].getBoundingClientRect(), b = q('.policy-mark')[0].getBoundingClientRect();
      const x1 = a.right - box.left + 8, y1 = a.top - box.top + a.height / 2, x2 = b.left - box.left + 40, y2 = b.top - box.top - 6;
      link.setAttribute('d', `M ${x1} ${y1} C ${x1 + 90} ${y1}, ${x2 - 20} ${y2 - 90}, ${x2} ${y2}`);
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(stage);
    const reply = SplitText.create(q('.reply')[0], { type: 'words,chars' });
    scrollStory(el.closest('section')!, el, () => gsap.timeline()
      .from(q('.msg-user'), { autoAlpha: 0, y: 16, duration: 0.5 })
      .from(q('.typing'), { autoAlpha: 0, duration: 0.2 }, 0.4)
      .to(q('.typing'), { autoAlpha: 0, duration: 0.2 }, 1.0)
      .from(q('.msg-bot'), { autoAlpha: 0, y: 12, duration: 0.3 }, 1.0)
      .from(reply.chars, { autoAlpha: 0, stagger: 0.025, duration: 0.01, ease: 'none' }, 1.1)
      .from(q('.policy'), { autoAlpha: 0, x: 40, rotate: 3, duration: 0.8, ease: 'expo.out' })
      .fromTo(q('.policy-mark'), { backgroundSize: '0% 100%' }, { backgroundSize: '100% 100%', duration: 0.5, ease: 'none' })
      .fromTo(q('.link'), { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 0.8, ease: 'power2.inOut' })
      .to(q('.wrong'), { color: '#ff7a5c', textShadow: '0 0 18px rgb(255 90 54 / 0.8)', duration: 0.3 }, '<')
      .from(q('.verdict-card'), { autoAlpha: 0, y: 30, scale: 0.96, duration: 0.7, ease: 'expo.out' }));
    return () => observer.disconnect();
  }, { scope: root });

  return (
    <div ref={root}>
      <div className="stage relative">
        <div className={`glass beam ${TONE.violet.beam} ${TONE.violet.glow} rounded-3xl p-5 sm:p-7 lg:mr-24`}>
          <div className="flex items-center gap-3 border-b border-line pb-4">
            <span className="relative grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-violet to-blue text-sm font-semibold">S</span>
            <div><div className="text-sm font-medium">Support assistant</div><div className="flex items-center gap-1.5 text-xs text-muted"><span className="h-1.5 w-1.5 rounded-full bg-ok" />online</div></div>
          </div>
          <div className="mt-5 space-y-4 text-[0.95rem]">
            <div className="msg-user ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-white/10 px-4 py-3">
              I bought the annual plan 45 days ago. Can I still get a refund?
            </div>
            <div className="typing flex w-fit gap-1 rounded-2xl bg-violet/15 px-4 py-3" aria-hidden="true">
              {[0, 1, 2].map(i => <span key={i} className="pulse-dot h-1.5 w-1.5 rounded-full bg-ink-2" style={{ animationDelay: `${i * 0.15}s` }} />)}
            </div>
            <div className="msg-bot max-w-[85%] rounded-2xl rounded-bl-md border border-violet/30 bg-violet/15 px-4 py-3">
              <span className="reply">Yes! Refunds are available within <span className="wrong font-semibold">60 days</span> of purchase, so you're covered.</span>
            </div>
          </div>
        </div>
        <div className="policy glass relative z-10 -mt-5 ml-auto w-[88%] rounded-2xl border-gold/30 p-5 sm:w-[66%] lg:mr-[-2%] lg:w-[58%]">
          <div className="t-label flex items-center justify-between text-muted"><span>Refund policy · section 4.2</span><span className="text-gold">Answer key</span></div>
          <p className="mt-3 text-[0.92rem] leading-relaxed text-ink-2">
            <span className="policy-mark rounded-sm bg-no-repeat text-ink [background-image:linear-gradient(rgb(255_200_97/0.25),rgb(255_200_97/0.25))]">Refunds must be requested within 30 days of purchase.</span>{' '}
            After 30 days, plans can be cancelled but not refunded.
          </p>
        </div>
        <svg className="pointer-events-none absolute inset-0 hidden h-full w-full overflow-visible lg:block" aria-hidden="true">
          <path className="link" pathLength={1} fill="none" stroke="#ff5a36" strokeWidth="2" strokeDasharray="1" strokeDashoffset="0" strokeLinecap="round" style={{ filter: 'drop-shadow(0 0 6px #ff5a36)' }} />
        </svg>
      </div>
      <div className="verdict-card glass mt-6 rounded-2xl p-5 lg:w-[80%]">
        <div className="flex flex-wrap items-center gap-3">
          <VerdictChip verdict="CONTRADICTED" />
          <span className="text-sm text-ink-2">by your refund policy, section 4.2</span>
        </div>
        <p className="mt-4 text-[0.95rem] text-ink"><span className="text-muted">Corrected answer: </span>Refunds are available within 30 days of purchase. After that you can cancel, but we can't refund the plan.</p>
      </div>
      <Illustration>Illustration · invented example</Illustration>
    </div>
  );
}

export function Audiences() {
  return (
    <div id="who">
      <AudienceSection
        id="product-teams" tone="cyan" audience="product-teams" kicker="For AI product teams"
        pitch="Switching models? See exactly which answers broke, before your users do."
        body={<>
          <p>Model makers retire models on their schedule, not yours. And answers can change silently, even while the model name stays the same.</p>
          <p>TrustLayer re-runs your real questions on the old and new model and shows which answers broke, which changed, and why.</p>
        </>}
        stats={[
          { value: <Scramble text="14 Jan 2027" />, caption: 'The day OpenAI removes GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini from its API. The notice went out on 14 October 2026.', cite: ['openaiDeprecations'] },
          { value: <Scramble text="84% → 51%" />, caption: 'GPT-4 on the same prime-number questions in March and then June 2023. Same model name, different answers.', cite: ['drift'] },
        ]}
        visual={<ModelSwitch />}
      />
      <AudienceSection
        id="documents" tone="gold" audience="documents" kicker="For lawyers, consultants and researchers"
        pitch="Paste your AI-written report. Every claim and citation checked, with proof."
        body={<>
          <p>AI drafts now go out under real names: briefs, client reports, research. One invented case or misquoted number can undo the whole document.</p>
          <p>TrustLayer checks whether each cited source exists, whether it says what your sentence says, and whether quotes appear word for word.</p>
        </>}
        stats={[
          { value: <Counter value={2199} />, caption: 'Legal decisions involving AI-hallucinated content, mostly fake citations, listed in a public database as of 16 October 2026.', cite: ['hallucinationCases'] },
          { value: <Counter value={97000} prefix="A$" suffix="+" />, caption: 'Refunded by Deloitte to the Australian government after its report was found to contain a fabricated court quote and references to papers that do not exist.', cite: ['deloitteErrors', 'deloitteRefund'] },
        ]}
        visual={<DocumentCheck />}
      />
      <AudienceSection
        id="support-bots" tone="violet" audience="support-bots" kicker="For customer-support bots"
        pitch="Your bot quoted the wrong policy today. Here's which answers, and why."
        body={<>
          <p>Your bot speaks for your company, and courts treat it that way. Give TrustLayer your own policy as the answer key.</p>
          <p>It checks what the bot told customers against that policy and shows each wrong answer, the line it broke, and the corrected answer.</p>
        </>}
        stats={[
          { value: <Counter value={650.88} decimals={2} prefix="C$" />, caption: 'Damages, plus interest and fees, that a tribunal ordered Air Canada to pay after its chatbot gave a customer wrong bereavement-fare rules. The airline argued the chatbot was responsible for its own actions. The tribunal rejected that.', cite: ['airCanada'] },
        ]}
        visual={<SupportBot />}
      />
    </div>
  );
}
