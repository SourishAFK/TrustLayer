import { useRef } from 'react';
import { Marquee } from '../../fx/fx';
import { INCIDENTS, SOURCES, sourceNumber } from '../../lib/content';
import { gsap, reducedMotion, SplitText, useGSAP } from '../../lib/motion';

function Incident({ item }: { item: (typeof INCIDENTS)[number] }) {
  return (
    <a href={SOURCES[item.source].url} target="_blank" rel="noreferrer" data-cursor="Source"
      className="glass flex shrink-0 items-center gap-3 rounded-full py-2.5 pl-3.5 pr-5 text-[0.95rem] text-ink-2 transition-colors hover:text-ink">
      <span className="pulse-dot h-2 w-2 rounded-full bg-ember shadow-[0_0_12px_#ff5a36]" />
      {item.text}
      <span className="font-mono text-xs text-muted">{item.when} · [{sourceNumber(item.source)}]</span>
    </a>
  );
}

/** Real, cited incidents scroll by in two opposing rows. */
export function Ticker() {
  return (
    <section aria-label="Recent incidents" className="relative z-10 space-y-4 border-y border-line bg-bg/40 py-8 backdrop-blur-[2px]">
      <Marquee speed={90}>{INCIDENTS.map(i => <Incident key={i.text} item={i} />)}</Marquee>
      <Marquee speed={110} reverse>{[...INCIDENTS].reverse().map(i => <Incident key={i.text} item={i} />)}</Marquee>
    </section>
  );
}

/** A sentence that lights up word by word as you scroll through it. */
export function Statement() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    if (reducedMotion()) return;
    const split = SplitText.create(root.current!.querySelector('p')!, { type: 'words' });
    gsap.fromTo(split.words, { opacity: 0.12 }, {
      opacity: 1, stagger: 0.08, ease: 'none',
      scrollTrigger: { trigger: root.current, start: 'top 75%', end: 'bottom 55%', scrub: true },
    });
  }, { scope: root });
  return (
    <section ref={root} id="statement" className="relative z-10 mx-auto max-w-6xl px-6 py-40 md:py-56">
      <p className="t-display max-w-[22ch]">
        Every AI answer is a promise someone will act on. Most are right. The wrong ones cost{' '}
        <span className="serif-em text-[#ff6a45]">money</span>,{' '}
        <span className="serif-em text-[#ff6a45]">customers</span> and{' '}
        <span className="serif-em text-[#ff6a45]">court time</span>.
      </p>
    </section>
  );
}
