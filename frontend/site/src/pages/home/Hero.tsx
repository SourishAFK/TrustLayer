import { useRef } from 'react';
import { Aurora, Cta, Kicker, VerdictChip } from '../../fx/fx';
import { introDone } from '../../fx/Preloader';
import type { Verdict } from '../../lib/content';
import { gsap, reducedMotion, SplitText, useGSAP } from '../../lib/motion';

// Illustrations of what a check returns. Each mirrors a rule the engine really applies.
const CLAIMS: { text: string; verdict: Verdict; proof: string; place: string }[] = [
  { text: 'Refunds are available within 60 days.', verdict: 'CONTRADICTED', proof: 'Your refund policy says 30 days', place: 'left-[0%] top-[0%]' },
  { text: 'The Eiffel Tower was completed in 1889.', verdict: 'SUPPORTED', proof: 'Quoted from two independent sources', place: 'right-[-6%] top-[25%]' },
  { text: 'Revenue grew 50% from $10M to $30M last year.', verdict: 'CONTRADICTED', proof: 'The math: $10M to $30M is +200%, not +50%', place: 'left-[-2%] top-[55%]' },
  { text: 'We are the only lender with instant approval.', verdict: 'UNVERIFIED', proof: 'No search can prove a claim about every lender', place: 'right-[-2%] top-[78%]' },
];

const CHECKS = ['Claims', 'Citations', 'Math', 'Your policy', 'Pushback', 'Drift'];

export function Hero() {
  const root = useRef<HTMLElement>(null);

  useGSAP((_, contextSafe) => {
    const q = gsap.utils.selector(root);
    if (reducedMotion()) return;
    gsap.set(q('.rise'), { y: 30, opacity: 0, filter: 'blur(8px)' });
    gsap.set(q('.claim'), { y: 60, opacity: 0, rotate: (i: number) => (i % 2 ? 4 : -4) });
    gsap.set(q('.result, .proof'), { autoAlpha: 0 });
    gsap.set(q('.pending'), { autoAlpha: 1 });
    const play = contextSafe!(() => {
      const split = SplitText.create(q('h1')[0], { type: 'words,chars', mask: 'words' });
      gsap.timeline()
        .from(split.chars, { yPercent: 115, opacity: 0, stagger: 0.012, duration: 1.4, ease: 'expo.out' })
        .from(q('.scribble'), { drawSVG: '0%', duration: 1.1, ease: 'power2.inOut' }, '-=0.6')
        .to(q('.rise'), { y: 0, opacity: 1, filter: 'blur(0px)', stagger: 0.09, duration: 1.2 }, '-=1.3')
        .to(q('.claim'), { y: 0, opacity: 1, rotate: 0, stagger: 0.14, duration: 1.6 }, '-=1.4');
      // Each card keeps "checking" forever: spinner, then its verdict decodes in.
      q('.claim').forEach((card, i) => {
        gsap.to(card, { y: i % 2 ? 14 : -14, duration: 3 + i * 0.4, ease: 'sine.inOut', yoyo: true, repeat: -1, delay: 2 + i * 0.3 });
        const [pending, result, proof] = ['.pending', '.result', '.proof'].map(s => card.querySelector(s));
        gsap.timeline({ repeat: -1, repeatDelay: 1.5, delay: 2.2 + i * 0.9 })
          .set(result, { autoAlpha: 0 }).set(proof, { autoAlpha: 0 }).set(pending, { autoAlpha: 1 })
          .to(pending, { autoAlpha: 0, duration: 0.2 }, 1.8)
          .fromTo(result, { autoAlpha: 0, scale: 0.8 }, { autoAlpha: 1, scale: 1, duration: 0.6, ease: 'back.out(2)' }, 1.9)
          .fromTo(proof, { autoAlpha: 0, y: 6 }, { autoAlpha: 1, y: 0, duration: 0.5 }, 2.1)
          .to({}, { duration: 4.5 });
      });
    });
    introDone.then(play);
  }, { scope: root });

  return (
    <section ref={root} id="top" className="relative flex min-h-[100svh] items-center overflow-hidden pb-16 pt-32">
      <Aurora blobs={[
        { c: 'rgb(59 108 255 / 0.20)', x: '45%', y: '-25%' },
        { c: 'rgb(139 92 255 / 0.16)', x: '-15%', y: '35%' },
        { c: 'rgb(255 90 54 / 0.08)', x: '70%', y: '55%', s: '40vmax' },
      ]} />
      <div className="grid-lines pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="relative z-10 mx-auto grid w-full max-w-7xl gap-14 px-6 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <div className="rise">
            <a href="/demo/?preset=support" data-cursor="Try it"><Kicker tone="ember">New · Check a bot against its own policy</Kicker></a>
          </div>
          <h1 className="t-hero mt-8 max-w-[15ch]">
            Catch your AI's mistakes before your customers, clients or{' '}
            <span className="judge relative inline-block whitespace-nowrap text-[#ff6a45] [text-shadow:0_0_40px_rgb(255_90_54/0.45)]">
              <span className="serif-em">a judge</span>
              <svg className="pointer-events-none absolute -bottom-3 left-0 h-4 w-full overflow-visible" viewBox="0 0 200 16" preserveAspectRatio="none" aria-hidden="true">
                <path className="scribble" d="M3 11 C 40 4, 90 3, 130 7 S 185 12, 197 5" fill="none" stroke="#ff5a36" strokeWidth="3" strokeLinecap="round" />
              </svg>
            </span>{' '}do.
          </h1>
          <p className="rise mt-8 max-w-xl text-lg text-ink-2 sm:text-xl">
            TrustLayer checks every claim in an AI answer against real sources, re-checks after every model, prompt or
            policy change, and tests whether the AI caves when pushed back.
          </p>
          <div className="rise mt-10 flex flex-wrap items-center gap-3">
            <Cta href="/check/?for=general" cursor="Free">Get a free check</Cta>
            <Cta href="/demo/" variant="ghost" cursor="Watch">Watch it check an answer</Cta>
          </div>
          <ul className="rise t-label mt-12 flex flex-wrap gap-x-5 gap-y-2 text-muted" aria-label="What it checks">
            {CHECKS.map(c => <li key={c} className="flex items-center gap-2"><span className="h-1 w-1 rounded-full bg-cyan shadow-[0_0_8px_#38d6ff]" />{c}</li>)}
          </ul>
        </div>
        <div className="relative hidden h-[600px] self-center lg:col-span-5 lg:block" aria-label="Examples of checked claims (illustrative)">
          {CLAIMS.map(c => (
            <div key={c.text} className={`claim glass spotlight absolute w-[244px] rounded-2xl p-3.5 ${c.place}`} data-tilt>
              <div className="flex items-center justify-between gap-3">
                <span className="t-label text-muted">Claim</span>
                <span className="relative grid">
                  <span className="pending t-label invisible col-start-1 row-start-1 flex items-center gap-2 text-ink-2">
                    <span className="h-3 w-3 animate-spin rounded-full border border-cyan border-t-transparent" /> Checking
                  </span>
                  <span className="result col-start-1 row-start-1"><VerdictChip verdict={c.verdict} /></span>
                </span>
              </div>
              <p className="mt-2.5 text-[0.88rem] leading-snug text-ink">{c.text}</p>
              <p className="proof mt-2.5 border-t border-line pt-2.5 font-mono text-[0.68rem] leading-relaxed text-ink-2">{c.proof}</p>
            </div>
          ))}
          <p className="t-label absolute -bottom-8 left-0 text-muted/70">Illustrative examples</p>
        </div>
      </div>
      <div className="no-print absolute bottom-6 left-1/2 hidden -translate-x-1/2 flex-col items-center gap-2 text-muted md:flex" aria-hidden="true">
        <span className="t-label">Scroll</span>
        <span className="relative h-10 w-px overflow-hidden bg-white/10">
          <span className="absolute inset-x-0 top-0 h-1/2 animate-[scrollcue_1.8s_ease-in-out_infinite] bg-gradient-to-b from-transparent to-cyan" />
        </span>
      </div>
    </section>
  );
}
