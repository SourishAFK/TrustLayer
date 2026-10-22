import { useRef } from 'react';
import { Aurora, Cta, Kicker } from '../../fx/fx';
import { Arrow } from '../../fx/icons';
import { gsap, reducedMotion, useGSAP } from '../../lib/motion';
import { PRESETS, type PresetId } from '../../lib/presets';

const GETS = [
  'A one-line result your boss will read',
  'Every wrong answer, with the source that proves it, the risk, and the fix',
  'Every correct answer your bot gave up under pushback',
  'What we did not test, stated plainly',
];

/** The report as a fanned stack of pages that squares up as you scroll. */
export function ReportTeaser() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    if (reducedMotion()) return;
    const q = gsap.utils.selector(root);
    // The fan is narrower on phones: at full spread the back pages reached past the screen edge.
    const k = window.innerWidth < 640 ? 0.35 : 1;
    gsap.fromTo(q('.page'), { rotateY: -28 * k, rotateX: 12 * k, rotateZ: (i: number) => (-8 + i * 5) * k, x: (i: number) => i * 46 * k, y: (i: number) => i * -26 * k },
      { rotateY: -10 * k, rotateX: 4 * k, rotateZ: (i: number) => (-2 + i * 2) * k, x: (i: number) => i * 22 * k, y: (i: number) => i * -14 * k, ease: 'none',
        scrollTrigger: { trigger: root.current, start: 'top bottom', end: 'bottom 40%', scrub: 1 } });
  }, { scope: root });

  return (
    <section ref={root} id="report" className="relative overflow-x-clip py-32 md:py-44">
      <Aurora blobs={[{ c: 'rgb(255 200 97 / 0.08)', x: '55%', y: '15%' }, { c: 'rgb(59 108 255 / 0.12)', x: '0%', y: '40%' }]} />
      <div className="relative z-10 mx-auto grid max-w-7xl items-center gap-16 px-6 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <Kicker tone="gold">The Bot Check-up</Kicker>
          <h2 data-split className="t-display mt-7">What you get: a report you can act on today.</h2>
          <ul className="mt-10 space-y-4">
            {GETS.map(g => (
              <li key={g} data-reveal className="flex gap-4 text-lg text-ink-2">
                <Arrow className="mt-1.5 h-4 w-4 shrink-0 text-gold" />{g}
              </li>
            ))}
          </ul>
          <div data-reveal className="mt-12 flex flex-wrap gap-3">
            <Cta href="/report/sample/" cursor="Read">Read a sample report</Cta>
          </div>
          <p data-reveal className="mt-4 text-sm text-muted">The sample uses a fictional lender and invented results.</p>
        </div>
        <div className="relative h-[460px] [perspective:1400px] sm:h-[540px] lg:col-span-7" aria-hidden="true">
          {[0, 1, 2].map(i => (
            <div key={i} className="page absolute left-[6%] top-[10%] w-[78%] rounded-2xl bg-paper p-6 text-paper-ink shadow-[0_40px_120px_-30px_rgb(0_0_0/0.9),0_0_0_1px_rgb(255_255_255/0.1)] [transform-style:preserve-3d] sm:p-8"
              style={{ zIndex: 3 - i, transform: `rotateY(-12deg) rotateZ(${-2 + i * 2}deg) translate(${i * 22}px, ${i * -14}px)` }}>
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.18em] text-[#6b7080]">
                <span>TrustLayer · Bot Check-up</span><span>Sample</span>
              </div>
              <div className="mt-6 font-serif text-3xl leading-tight">The bot got 82 of 100 questions right.</div>
              <p className="mt-2 text-sm text-[#4a4f5c]">7 wrong answers could cost a customer money. It dropped 4 correct answers when pushed back.</p>
              <div className="mt-6 flex h-3 gap-[2px] overflow-hidden rounded-[4px]">
                <span className="bg-ok" style={{ width: '82%' }} /><span className="bg-bad" style={{ width: '9%' }} />
                <span className="bg-warn" style={{ width: '6%' }} /><span className="bg-neutral" style={{ width: '3%' }} />
              </div>
              <div className="mt-6 space-y-3">
                {['Prepayment charge stated as zero', 'Processing fee miscalculated', 'Lowest rate in India claim'].map(t => (
                  <div key={t} className="flex items-center justify-between rounded-lg border border-black/10 px-3 py-2 text-sm">
                    <span>{t}</span><span className="text-xs font-semibold uppercase tracking-[0.12em] text-bad">Wrong</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function DemoBand() {
  return (
    <section id="demo-band" className="relative overflow-hidden py-28">
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <div data-reveal className="glass beam spotlight overflow-hidden rounded-[2rem] p-8 sm:p-12">
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <div>
              <Kicker>Live demo</Kicker>
              <h2 data-split className="t-display mt-7">Watch it check an answer, claim by claim.</h2>
              <p className="mt-6 max-w-md text-lg text-ink-2">Paste any AI answer, or try one of three examples. The checks stream in as they run.</p>
              <div className="mt-10"><Cta href="/demo/" cursor="Try">Open the live demo</Cta></div>
            </div>
            <ul className="space-y-3">
              {(Object.keys(PRESETS) as PresetId[]).map(id => (
                <li key={id}>
                  <a href={`/demo/?preset=${id}`} data-tilt data-cursor="Try"
                    className="group flex items-center justify-between gap-6 rounded-2xl border border-line bg-white/[0.03] p-5 transition-colors hover:border-cyan/40 hover:bg-cyan/[0.06]">
                    <span>
                      <span className="t-label text-muted">{PRESETS[id].name}</span>
                      <span className="mt-2 block text-sm text-ink-2">{PRESETS[id].blurb}</span>
                    </span>
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-line-2 transition-colors group-hover:border-cyan group-hover:bg-cyan group-hover:text-bg">
                      <Arrow className="h-4 w-4" />
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
