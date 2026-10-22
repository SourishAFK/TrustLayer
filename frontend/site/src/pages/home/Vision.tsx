import { useRef } from 'react';
import { Cta, Kicker, Meteors } from '../../fx/fx';
import { gsap, reducedMotion, useGSAP } from '../../lib/motion';

const LADDER = [
  { when: 'Now', name: 'Bot Check-up', text: 'A one-time check of your bot: every wrong answer, with proof and the fix.' },
  { when: 'Building', name: 'Trust Clock', text: 'The same questions every day, and an alarm when answers drift.' },
  { when: 'Next', name: 'Stop bad answers', text: 'Catch a wrong answer before it reaches the customer.' },
  { when: 'The goal', name: 'A trust grade', text: 'An independent grade for any AI, open for anyone to look up.' },
];

const LANES = ['Lending', 'Insurance', 'Healthcare', 'Legal', 'Public services', 'Education'];

export function Vision() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    if (reducedMotion()) return;
    const q = gsap.utils.selector(root);
    gsap.fromTo(q('.rail'), { scaleX: 0 }, { scaleX: 1, ease: 'none', scrollTrigger: { trigger: q('.ladder')[0], start: 'top 80%', end: 'bottom 55%', scrub: 1 } });
    gsap.from(q('.rung'), { y: 40, opacity: 0, stagger: 0.15, duration: 1.2, scrollTrigger: { trigger: q('.ladder')[0], start: 'top 80%', once: true } });
    gsap.from(q('.lane'), { scale: 0.6, opacity: 0, stagger: 0.06, duration: 0.9, ease: 'back.out(2)', scrollTrigger: { trigger: q('.lanes')[0], start: 'top 85%', once: true } });
  }, { scope: root });

  return (
    <section ref={root} id="vision" className="relative overflow-hidden py-32 md:py-48">
      <Meteors count={16} />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <Kicker tone="violet">Where we're going</Kicker>
        <h2 data-split className="t-hero mt-8 max-w-[12ch]">A trust grade for every AI.</h2>
        <p data-reveal className="mt-8 max-w-2xl text-xl text-ink-2">
          Today TrustLayer checks one bot at a time. Next it watches them every day, then stops a wrong answer before a
          customer sees it. The goal is one independent grade anyone can look up before relying on an AI, the way a
          lender checks a credit score.
        </p>

        <div className="ladder relative mt-20">
          <div className="absolute left-0 right-0 top-[11px] hidden h-px bg-white/10 lg:block" aria-hidden="true">
            <div className="rail h-full origin-left bg-[linear-gradient(90deg,#38d6ff,#8b5cff,#ff5ad1)] shadow-[0_0_14px_#8b5cff]" />
          </div>
          <ol className="grid gap-10 lg:grid-cols-4 lg:gap-8">
            {LADDER.map((r, i) => (
              <li key={r.name} className="rung relative">
                <span className={`relative z-10 block h-[23px] w-[23px] rounded-full border-2 ${i === 0 ? 'border-cyan bg-cyan shadow-[0_0_20px_#38d6ff]' : i === 1 ? 'border-violet bg-bg shadow-[0_0_16px_#8b5cff]' : 'border-white/30 bg-bg'}`} />
                <div className="t-label mt-6 text-muted">{r.when}</div>
                <div className="t-title mt-2">{r.name}</div>
                <p className="mt-3 max-w-xs text-ink-2">{r.text}</p>
              </li>
            ))}
          </ol>
        </div>

        <div data-reveal className="glass mt-24 rounded-3xl p-7 sm:p-10">
          <div className="grid gap-8 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-5">
              <h3 className="t-title">Built for the industries where one wrong answer costs real money.</h3>
              <p className="mt-4 text-ink-2">We show evidence. We never claim that a bot is approved by a regulator or compliant with a law.</p>
            </div>
            <ul className="lanes flex flex-wrap gap-3 lg:col-span-7 lg:justify-end">
              {LANES.map(l => (
                <li key={l} className="lane glass rounded-full px-5 py-2.5 text-ink">{l}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

export function FinalCta() {
  const lanes = [
    { href: '/check/?for=product-teams', title: 'AI product teams', text: 'Before and after every model switch.', tone: '' },
    { href: '/check/?for=documents', title: 'AI-written documents', text: 'Every claim and citation, with proof.', tone: 'beam-gold' },
    { href: '/check/?for=support-bots', title: 'Customer-support bots', text: 'Checked against your own policy.', tone: 'beam-violet' },
  ];
  return (
    <section id="start" className="relative overflow-hidden py-32 md:py-44">
      <div className="dots pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <h2 data-split className="t-hero max-w-[16ch]">Find out what your AI gets wrong before anyone else does.</h2>
        <ul className="mt-16 grid gap-3 md:grid-cols-3">
          {lanes.map(l => (
            <li key={l.href} data-reveal>
              <a href={l.href} data-tilt data-cursor="Free check"
                className={`glass beam spotlight group flex h-full flex-col justify-between gap-12 rounded-3xl p-7 ${l.tone}`}>
                <span>
                  <span className="t-title block">{l.title}</span>
                  <span className="mt-2 block text-ink-2">{l.text}</span>
                </span>
                <span className="flex items-center gap-2 font-medium text-ink">
                  Get a free check <span className="transition-transform duration-500 group-hover:translate-x-1.5">→</span>
                </span>
              </a>
            </li>
          ))}
        </ul>
        <div data-reveal className="mt-10 flex flex-wrap items-center gap-4 text-ink-2">
          Something else? <Cta href="/check/?for=general" variant="ghost" size="sm">Get a general check</Cta>
        </div>
      </div>
    </section>
  );
}
