import { useRef } from 'react';
import { Aurora, Kicker, VerdictChip } from '../../fx/fx';
import { Loop } from '../../fx/icons';
import { VERDICTS, type Verdict } from '../../lib/content';
import { gsap, scrollStory, useGSAP } from '../../lib/motion';

const STEPS = [
  { title: 'Split', text: 'We break the answer into separate claims, so one true sentence can never vouch for a false one next to it.' },
  { title: 'Check', text: 'Each claim goes to the check that can settle it: trusted sources, your own documents, the math, the citations, and whether the answer contradicts itself or has gone out of date.' },
  { title: 'Prove', text: 'Every verdict comes with the exact passage that decided it. If nothing trustworthy settles a claim, we say "unverified" instead of guessing.' },
  { title: 'Repeat', text: 'Then we push back, and run it all again after every model, prompt or policy change.' },
];

// The example mirrors rules the engine really applies.
const CLAIMS: { text: string; engine: string; verdict: Verdict; proof: string }[] = [
  { text: 'Acme was founded in 2012.', engine: 'Sources', verdict: 'SUPPORTED', proof: 'Company registry: “incorporated on 14 March 2012”' },
  { text: 'Revenue grew 50% from $10M to $30M last year.', engine: 'Math', verdict: 'CONTRADICTED', proof: '$10M to $30M is a 200% increase, not 50%' },
  { text: 'Customers can get a refund within 60 days.', engine: 'Your documents', verdict: 'CONTRADICTED', proof: 'Your refund policy, 4.2: “within 30 days of purchase”' },
  { text: 'Acme is the only provider in India with instant payouts.', engine: 'Sources', verdict: 'UNVERIFIED', proof: 'A claim about every provider cannot be proven by searching, so it is never marked supported' },
];

const ENGINES = ['Sources', 'Your documents', 'Math', 'Citations', 'Consistency', 'Freshness'];

export function HowItWorks() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    const el = root.current!;
    const q = gsap.utils.selector(el);
    const panel = q('.panel')[0];
    gsap.set(q('.verdict-row, .repeat, .found'), { autoAlpha: 0 });
    scrollStory(el, panel, () => {
      const tl = gsap.timeline({ defaults: { ease: 'power2.out' } });
      tl.to(q('.step-0'), { opacity: 1, duration: 0.2 });
      // Split
      q('.claim').forEach((claim, i) => {
        tl.fromTo(claim, { backgroundSize: '0% 2px' }, { backgroundSize: '100% 2px', duration: 0.5, ease: 'none' }, 0.2 + i * 0.35);
      });
      tl.fromTo(q('.found'), { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.3, immediateRender: false }, 1.6);
      // Check
      tl.to(q('.step-1'), { opacity: 1, duration: 0.2 }, 2.0);
      q('.claim').forEach((claim, i) => {
        const at = 2.1 + i * 0.5;
        const engine = q(`.engine[data-engine="${CLAIMS[i].engine}"]`);
        tl.fromTo(claim.querySelector('.tag'), { autoAlpha: 0, width: 0, marginLeft: 0, paddingLeft: 0, paddingRight: 0 },
          { autoAlpha: 1, width: 'auto', marginLeft: 8, paddingLeft: 8, paddingRight: 8, duration: 0.3 }, at)
          .fromTo(engine, { backgroundColor: 'rgb(56 214 255 / 0)', boxShadow: '0 0 0 0 rgb(56 214 255 / 0)' },
            { backgroundColor: 'rgb(56 214 255 / 0.16)', boxShadow: '0 0 30px -4px rgb(56 214 255 / 0.7)', duration: 0.25, yoyo: true, repeat: 1 }, at);
      });
      // Prove
      tl.to(q('.step-2'), { opacity: 1, duration: 0.2 }, 4.3)
        .fromTo(q('.verdict-row'), { autoAlpha: 0, x: -14 }, { autoAlpha: 1, x: 0, stagger: 0.3, duration: 0.4, immediateRender: false }, 4.4);
      // Repeat
      tl.to(q('.step-3'), { opacity: 1, duration: 0.2 }, 6.0)
        .fromTo(q('.repeat'), { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.4, immediateRender: false }, 6.1)
        .to(q('.loop-icon'), { rotate: 360, duration: 1.2, ease: 'none' }, 6.1);
      return tl;
    });
  }, { scope: root });

  return (
    <section ref={root} id="how" className="relative py-28 lg:py-0">
      <Aurora blobs={[{ c: 'rgb(59 108 255 / 0.14)', x: '55%', y: '20%' }, { c: 'rgb(56 214 255 / 0.08)', x: '-10%', y: '60%' }]} />
      <div className="relative z-10 mx-auto max-w-7xl px-6 lg:pt-36">
        <Kicker>How a check works</Kicker>
        <h2 data-split className="t-display mt-7 max-w-[18ch]">Four steps. Every verdict comes with its proof.</h2>
      </div>
      <div className="relative z-10 mx-auto max-w-7xl px-6 lg:grid lg:grid-cols-12 lg:gap-16">
        <ol className="mt-14 space-y-12 lg:col-span-4 lg:mt-0 lg:space-y-0">
          {STEPS.map((s, i) => (
            <li key={s.title} className={`step-${i} lg:flex lg:min-h-[62vh] lg:flex-col lg:justify-center lg:opacity-30`}>
              <h3 className="t-title">{s.title}</h3>
              <p className="mt-3 max-w-sm text-ink-2">{s.text}</p>
            </li>
          ))}
        </ol>
        <div className="mt-14 lg:col-span-8 lg:mt-0">
          <div className="panel glass beam spotlight rounded-3xl p-5 sm:p-7 lg:sticky lg:top-[12vh]">
            <div className="t-label flex items-center justify-between text-muted">
              <span>An AI answer</span>
              <span className="found text-ink-2">4 claims found</span>
            </div>
            <p className="mt-4 text-[1.05rem] leading-[2.1] text-ink">
              {CLAIMS.map(c => (
                <span key={c.text}>
                  <span className="claim relative bg-no-repeat pb-0.5 [background-image:linear-gradient(#38d6ff,#38d6ff)] [background-position:0_100%] [background-size:0%_2px]">
                    {c.text}
                    <span className="tag t-label ml-2 inline-block overflow-hidden whitespace-nowrap rounded-full border border-cyan/40 bg-cyan/10 px-2 py-0.5 align-middle text-[0.6rem] text-ice">→ {c.engine}</span>
                  </span>{' '}
                </span>
              ))}
            </p>
            <div className="mt-6 flex flex-wrap gap-2 border-y border-line py-4" aria-label="Checks">
              {ENGINES.map(e => (
                <span key={e} data-engine={e} className="engine t-label rounded-full border border-line-2 px-3 py-1.5 text-ink-2">{e}</span>
              ))}
            </div>
            <ul className="mt-5 space-y-3">
              {CLAIMS.map(c => (
                <li key={c.text} className="verdict-row grid gap-2 rounded-xl border border-line bg-white/[0.02] p-3 sm:grid-cols-[10.5rem_1fr] sm:items-center">
                  <VerdictChip verdict={c.verdict} className="w-fit" />
                  <span className="text-sm text-ink-2">{c.proof}</span>
                </li>
              ))}
            </ul>
            <div className="repeat mt-5 flex flex-wrap items-center gap-3 rounded-xl border border-violet/30 bg-violet/10 p-3 text-sm">
              <Loop className="loop-icon h-5 w-5 text-violet" />
              <span className="text-ink">Checked again after every model, prompt or policy change, and after pushback: <i className="serif-em text-base text-ink-2">“Are you sure?”</i></span>
            </div>
          </div>
        </div>
      </div>
      <div className="relative z-10 mx-auto mt-24 max-w-7xl px-6 lg:mt-10 lg:pb-10">
        <h3 data-reveal className="t-label text-muted">Five possible verdicts</h3>
        <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {(Object.keys(VERDICTS) as Verdict[]).map(v => (
            <li key={v} data-reveal data-tilt className="glass spotlight rounded-2xl p-5">
              <VerdictChip verdict={v} />
              <p className="mt-4 text-sm text-ink-2">{VERDICTS[v].meaning}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
