import { useRef, type ReactNode } from 'react';
import { Figure, StackBar } from '../../components/charts';
import type { Look } from '../../components/FieldCanvas';
import { mount, Shell } from '../../components/Shell';
import { Aurora, Cta, VerdictChip } from '../../fx/fx';
import { Arrow, Mark, Print } from '../../fx/icons';
import { VERDICTS, type Verdict } from '../../lib/content';
import { gsap, reducedMotion, useGSAP } from '../../lib/motion';
import report from './sample-report.json';

const LOOK: Look = {
  desktop: { x: 0, y: 0.3, scale: 1.6, tilt: -1.15, opacity: 0.32, morph: 0, speed: 0.6 },
  mobile: { x: 0, y: 0.3, scale: 0.8, tilt: -1.1, opacity: 0.2, morph: 0, speed: 0.6 },
};
const COLOR: Record<Verdict, string> = {
  SUPPORTED: '#08a4c6', CONTRADICTED: '#d43126', DISPUTED: '#8e3eae', UNVERIFIED: '#b4901a', 'NOT CHECKABLE': '#8a90a2',
};
const SEVERITY: Record<string, { label: string; bar: string; chip: string }> = {
  high: { label: 'High risk', bar: 'bg-bad', chip: 'border-bad/40 bg-bad/10 text-[#9c2219]' },
  medium: { label: 'Medium risk', bar: 'bg-warn', chip: 'border-warn/50 bg-warn/10 text-[#7a5f0c]' },
  low: { label: 'Low risk', bar: 'bg-neutral', chip: 'border-black/15 bg-black/5 text-[#4a4f5c]' },
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="break-inside-avoid-page border-t border-black/10 pt-10" data-reveal>
      <h2 className="font-serif text-[2rem] leading-tight tracking-[-0.01em] text-paper-ink">{title}</h2>
      <div className="mt-6">{children}</div>
    </section>
  );
}

function Report() {
  const paper = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (reducedMotion()) return;
    gsap.from(paper.current, { y: 120, rotateX: 14, opacity: 0, transformPerspective: 1600, transformOrigin: '50% 0%', duration: 1.6, ease: 'expo.out', delay: 0.15 });
    gsap.from('.toolbar', { y: -20, opacity: 0, duration: 1, delay: 0.5 });
  });
  const total = report.verdicts.reduce((sum, v) => sum + v.value, 0);

  return (
    <section className="relative overflow-hidden pb-24 pt-32 print:p-0">
      <Aurora blobs={[{ c: 'rgb(255 200 97 / 0.10)', x: '50%', y: '-10%' }, { c: 'rgb(59 108 255 / 0.14)', x: '-10%', y: '30%' }]} />
      <div className="relative z-10 mx-auto max-w-5xl px-4 sm:px-6 print:max-w-none print:px-0">
        <div className="toolbar no-print glass mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-3">
          <span className="flex items-center gap-2 text-sm text-ink-2">
            <span className="rounded-full border border-gold/50 bg-gold/15 px-2.5 py-0.5 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-gold">Sample</span>
            Fictional company, invented results
          </span>
          <span className="flex flex-wrap gap-2">
            <button type="button" onClick={() => window.print()} data-magnetic className="btn btn-ghost glass btn-sm">
              <Print className="h-4 w-4" /> Print or save as PDF
            </button>
            <Cta href="/check/?for=support-bots&from=sample-report" size="sm">Get your own check-up</Cta>
          </span>
        </div>

        <article ref={paper} className="paper rounded-[1.75rem] bg-paper px-6 py-10 text-paper-ink shadow-[0_60px_160px_-40px_rgb(0_0_0/0.9),0_0_0_1px_rgb(255_255_255/0.08)] sm:px-14 sm:py-16">
          <header>
            <div className="flex flex-wrap items-center justify-between gap-4 text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-[#5d6270]">
              <span className="flex items-center gap-2"><Mark size={22} light /> TrustLayer · Bot Check-up</span>
              <span>{report.report_id}</span>
            </div>
            <p className="mt-8 rounded-xl border border-[#b4901a]/40 bg-[#b4901a]/10 px-4 py-3 text-sm text-[#5b470a]">{report.sample_notice}</p>
            <h1 className="mt-10 font-serif text-[clamp(2.4rem,5vw,3.6rem)] leading-[1.02] tracking-[-0.02em]">{report.company}</h1>
            <p className="mt-3 text-lg text-[#3c404a]">{report.bot}</p>
            <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-4">
              <div><dt className="text-[#6b7080]">Tested</dt><dd className="mt-1 font-medium">{report.tested}</dd></div>
              <div><dt className="text-[#6b7080]">Issued</dt><dd className="mt-1 font-medium">{report.issued}</dd></div>
              {report.scope.slice(0, 2).map(s => <div key={s.label}><dt className="text-[#6b7080]">{s.label}</dt><dd className="mt-1 font-medium">{s.value}</dd></div>)}
            </dl>
          </header>

          <div className="mt-12 rounded-2xl bg-[#14161c] p-7 text-ink sm:p-9" data-reveal>
            <div className="t-label text-muted">The result in one line</div>
            <p className="mt-4 font-serif text-[clamp(1.5rem,3vw,2.1rem)] leading-snug">{report.headline}</p>
          </div>

          <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-reveal>
            {report.tiles.map(t => (
              <div key={t.label} className="rounded-2xl border border-black/10 p-5">
                <div className="text-sm text-[#4a4f5c]">{t.label}</div>
                <div className="mt-2 text-3xl font-semibold tracking-[-0.03em]">{t.value}</div>
                {t.note && <div className="mt-1 text-xs text-[#6b7080]">{t.note}</div>}
              </div>
            ))}
          </div>

          <div className="mt-10" data-reveal>
            <Figure light title={`All ${total} answers, by verdict`} subtitle="Each question's most common answer across its 5 runs"
              table={{ columns: ['Verdict', 'Answers'], rows: report.verdicts.map(v => [v.label, v.value]) }}>
              <StackBar light surface="#fbfaf7" parts={report.verdicts.map(v => ({
                label: v.label, value: v.value, color: COLOR[v.verdict as Verdict],
                tip: `${v.value} answers: ${VERDICTS[v.verdict as Verdict].meaning}`,
              }))} />
            </Figure>
          </div>

          <div className="mt-14 space-y-14">
            <Section title="Every wrong answer, with proof">
              <ol className="space-y-6">
                {report.findings.map(f => {
                  const sev = SEVERITY[f.severity];
                  return (
                    <li key={f.id} className="relative overflow-hidden rounded-2xl border border-black/10 bg-white p-6 pl-8 [break-inside:avoid]">
                      <span className={`absolute inset-y-0 left-0 w-1.5 ${sev.bar}`} aria-hidden="true" />
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="text-lg font-semibold"><span className="font-mono text-sm text-[#6b7080]">{f.id}</span> · {f.topic}</h3>
                        <span className="flex flex-wrap gap-2 text-xs">
                          <span className={`rounded-full border px-2.5 py-1 font-semibold uppercase tracking-[0.1em] ${sev.chip}`}>{sev.label}</span>
                          <span className="rounded-full border border-black/10 px-2.5 py-1 text-[#4a4f5c]">Seen in {f.seen}</span>
                        </span>
                      </div>
                      <dl className="mt-5 grid gap-4 text-[0.95rem] sm:grid-cols-[9rem_1fr]">
                        <dt className="text-[#6b7080]">Question</dt><dd>“{f.question}”</dd>
                        <dt className="text-[#6b7080]">The bot said</dt>
                        <dd className="flex flex-wrap items-start gap-3"><span className="font-medium">“{f.bot}”</span><VerdictChip verdict="CONTRADICTED" label="Wrong" className="text-paper-ink" /></dd>
                        <dt className="text-[#6b7080]">The proof</dt>
                        <dd><blockquote className="border-l-2 border-ok pl-4 font-serif text-lg leading-snug">“{f.quote}”</blockquote><div className="mt-1.5 text-xs text-[#6b7080]">{f.source}</div></dd>
                        <dt className="text-[#6b7080]">Why it matters</dt><dd>{f.risk}</dd>
                        <dt className="text-[#6b7080]">The fix</dt><dd className="font-medium">{f.fix}</dd>
                      </dl>
                    </li>
                  );
                })}
              </ol>
            </Section>

            <Section title="Correct answers it gave up under pushback">
              <p className="mb-6 max-w-2xl text-[#3c404a]">In {report.pushback.length} of 20 pushback tests the bot dropped a correct answer after a challenge that brought no new evidence.</p>
              <ol className="grid gap-4 md:grid-cols-2">
                {report.pushback.map(p => (
                  <li key={p.question} className="rounded-2xl border border-black/10 bg-white p-5 text-[0.92rem] [break-inside:avoid]">
                    <div className="font-medium">“{p.question}”</div>
                    <div className="mt-4 space-y-2.5">
                      <p className="rounded-xl bg-[#08a4c6]/10 px-3 py-2"><span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#0b6f86]">First answer · right</span><br />{p.first}</p>
                      <p className="ml-6 rounded-xl bg-black/5 px-3 py-2"><span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#4a4f5c]">Customer</span><br />{p.challenge}</p>
                      <p className="rounded-xl bg-[#d43126]/10 px-3 py-2"><span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#9c2219]">After pushback · wrong</span><br />{p.after}</p>
                    </div>
                    <p className="mt-3 text-xs text-[#4a4f5c]">{p.why}</p>
                  </li>
                ))}
              </ol>
            </Section>

            <Section title="What we did not test">
              <ul className="list-disc space-y-2 pl-5 text-[#3c404a]">{report.not_tested.map(n => <li key={n}>{n}</li>)}</ul>
            </Section>

            <Section title="How we checked">
              <ul className="list-disc space-y-2 pl-5 text-[#3c404a]">{report.method.map(m => <li key={m}>{m}</li>)}</ul>
              <p className="mt-5 text-sm text-[#4a4f5c]"><span className="font-medium text-paper-ink">Answer key used:</span> {report.answer_key.join(' · ')}</p>
            </Section>

            <Section title="What to do next">
              <p className="max-w-3xl text-lg leading-relaxed">{report.next}</p>
            </Section>
          </div>

          <footer className="mt-16 border-t border-black/10 pt-6 text-xs leading-relaxed text-[#6b7080]">
            <p>{report.disclaimer}</p>
            <p className="mt-2">{report.sample_notice}</p>
          </footer>
        </article>

        <div className="no-print mt-14 flex flex-col items-center gap-5 text-center">
          <p className="t-title max-w-xl">Want this for your bot? The first check is free.</p>
          <div className="flex flex-wrap justify-center gap-3">
            <Cta href="/check/?for=support-bots&from=sample-report">Get a free check</Cta>
            <a href="/demo/?preset=support" className="btn btn-ghost glass beam">Try the live demo <Arrow className="arrow h-4 w-4" /></a>
          </div>
        </div>
      </div>
    </section>
  );
}

mount(<Shell look={LOOK}><Report /></Shell>);
