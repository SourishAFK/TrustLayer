import { useMemo, useRef, type ReactNode } from 'react';
import { SOURCES, sourceNumber, VERDICTS, type SourceKey, type Verdict } from '../lib/content';
import { finePointer, gsap, reducedMotion, ScrollTrigger, useGSAP } from '../lib/motion';
import { Arrow, VERDICT_ICON } from './icons';

export const Grain = () => <div className="grain" aria-hidden="true" />;

type Blob = { c: string; x: string; y: string; s?: string };
export function Aurora({ blobs, className = '' }: { blobs: Blob[]; className?: string }) {
  return (
    <div className={`aurora ${className}`} aria-hidden="true">
      {blobs.map((b, i) => (
        <i key={i} style={{ '--c': b.c, left: b.x, top: b.y, width: b.s, height: b.s } as React.CSSProperties} />
      ))}
    </div>
  );
}

/** Falling light streaks. Keep them out of text: pass a className that masks or hides them there. */
export function Meteors({ count = 14, className = '' }: { count?: number; className?: string }) {
  const meteors = useMemo(() => Array.from({ length: count }, (_, i) => ({
    left: `${(i * 37) % 100}%`, top: `${(i * 53) % 60 - 10}%`,
    d: `${6 + ((i * 7) % 6)}s`, delay: `${(i * 1.7) % 9}s`,
  })), [count]);
  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`} aria-hidden="true">
      {meteors.map((m, i) => (
        <span key={i} className="meteor" style={{ left: m.left, top: m.top, '--d': m.d, '--delay': m.delay } as React.CSSProperties} />
      ))}
    </div>
  );
}

export function Marquee({ children, reverse = false, speed = 70 }: { children: ReactNode; reverse?: boolean; speed?: number }) {
  return (
    <div className="marquee-wrap overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_12%,#000_88%,transparent)]">
      <div className={`marquee ${reverse ? 'marquee-reverse' : ''}`} style={{ '--speed': `${speed}s` } as React.CSSProperties}>
        <div className="flex shrink-0 gap-4 pr-4">{children}</div>
        <div className="flex shrink-0 gap-4 pr-4" aria-hidden="true">{children}</div>
      </div>
    </div>
  );
}

/** Counts up to `value` when scrolled into view. */
export function Counter({ value, decimals = 0, prefix = '', suffix = '', className = '' }: {
  value: number; decimals?: number; prefix?: string; suffix?: string; className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const format = (n: number) => `${prefix}${n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
  useGSAP(() => {
    const el = ref.current;
    if (!el || reducedMotion()) return;
    const counter = { n: 0 };
    el.textContent = format(0);
    el.style.fontVariantNumeric = 'tabular-nums'; // steady width while counting; proportional at rest
    gsap.to(counter, {
      n: value, duration: 2.2, ease: 'expo.out',
      onUpdate: () => { el.textContent = format(counter.n); },
      onComplete: () => { el.style.fontVariantNumeric = ''; },
      scrollTrigger: { trigger: el, start: 'top 92%', once: true },
    });
  }, { scope: ref });
  return <span ref={ref} className={className}>{format(value)}</span>;
}

/** Text that decodes itself (ScrambleText) when it scrolls into view. */
export function Scramble({ text, className = '', delay = 0 }: { text: string; className?: string; delay?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  useGSAP(() => {
    if (!ref.current || reducedMotion()) return;
    gsap.from(ref.current, {
      duration: 1.4, delay, ease: 'none',
      scrambleText: { text: '', chars: '01#%&*+=<>/\\ABCDEFGHJKLMNPQRSTUVWXYZ', speed: 0.6, revealDelay: 0.2 },
      scrollTrigger: { trigger: ref.current, start: 'top 92%', once: true },
    });
  }, { scope: ref });
  return <span ref={ref} className={className}>{text}</span>;
}

export function ScrollProgress() {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    gsap.fromTo(ref.current, { scaleX: 0 }, {
      scaleX: 1, ease: 'none',
      scrollTrigger: { start: 0, end: () => ScrollTrigger.maxScroll(window), scrub: 0.3 },
    });
  });
  return (
    <div aria-hidden="true" className="no-print fixed inset-x-0 top-0 z-[60] h-[2px]">
      <div ref={ref} className="h-full origin-left bg-[linear-gradient(90deg,#38d6ff,#8b5cff,#ff5a36)] shadow-[0_0_14px_#38d6ff]" />
    </div>
  );
}

/** A numbered citation that links to its source; the full list sits in the footer. */
export function Cite({ k }: { k: SourceKey }) {
  const s = SOURCES[k];
  return (
    <a href={s.url} target="_blank" rel="noreferrer" title={`${s.title} — ${s.by}, ${s.date}`}
      className="ml-0.5 align-super font-mono text-xs text-cyan hover:text-ice" data-cursor="Source">
      [{sourceNumber(k)}]
    </a>
  );
}

export function VerdictChip({ verdict, label, className = '' }: { verdict: Verdict; label?: string; className?: string }) {
  const Icon = VERDICT_ICON[verdict];
  const v = VERDICTS[verdict];
  return <span className={`chip ${v.cls} ${className}`}><Icon />{label ?? v.label}</span>;
}

export function Cta({ href, children, variant = 'primary', size, cursor, className = '' }: {
  href: string; children: ReactNode; variant?: 'primary' | 'ghost'; size?: 'sm'; cursor?: string; className?: string;
}) {
  const look = variant === 'primary' ? 'btn-primary' : 'btn-ghost glass beam';
  return (
    <a href={href} data-magnetic data-cursor={cursor} className={`btn ${look} ${size === 'sm' ? 'btn-sm' : ''} ${className}`}>
      <span className="relative z-[2]">{children}</span>
      <Arrow className="arrow relative z-[2] h-4 w-4" />
    </a>
  );
}

export function Kicker({ children, tone = 'cyan' }: { children: ReactNode; tone?: 'cyan' | 'ember' | 'gold' | 'violet' }) {
  const dot = { cyan: 'bg-cyan', ember: 'bg-ember', gold: 'bg-gold', violet: 'bg-violet' }[tone];
  return (
    <span className="t-label glass inline-flex items-center gap-2.5 rounded-full px-3.5 py-1.5 text-ink-2">
      <span className={`pulse-dot h-1.5 w-1.5 rounded-full ${dot} shadow-[0_0_10px_currentColor]`} />
      {children}
    </span>
  );
}

/**
 * Pointer effects by delegation, so elements rendered later get them too:
 * .spotlight follows the cursor, [data-magnetic] leans toward it, [data-tilt] tilts in 3D.
 */
export function bindPointerEffects() {
  if (!finePointer() || reducedMotion()) return () => {};
  let magnet: HTMLElement | null = null;
  let tilt: HTMLElement | null = null;
  const release = (el: HTMLElement | null, props: gsap.TweenVars) => el && gsap.to(el, { ...props, duration: 0.9, ease: 'elastic.out(1, 0.4)' });
  const onMove = (e: PointerEvent) => {
    const target = e.target as Element | null;
    const spot = target?.closest<HTMLElement>('.spotlight');
    if (spot) {
      const r = spot.getBoundingClientRect();
      spot.style.setProperty('--mx', `${e.clientX - r.left}px`);
      spot.style.setProperty('--my', `${e.clientY - r.top}px`);
    }
    const m = target?.closest<HTMLElement>('[data-magnetic]') ?? null;
    if (m !== magnet) { release(magnet, { x: 0, y: 0 }); magnet = m; }
    if (m) {
      const r = m.getBoundingClientRect();
      gsap.to(m, { x: (e.clientX - r.left - r.width / 2) * 0.28, y: (e.clientY - r.top - r.height / 2) * 0.35, duration: 0.6, ease: 'power3.out' });
    }
    const t = target?.closest<HTMLElement>('[data-tilt]') ?? null;
    if (t !== tilt) { release(tilt, { rotateX: 0, rotateY: 0 }); tilt = t; }
    if (t) {
      const r = t.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      gsap.to(t, { rotateY: px * 9, rotateX: -py * 9, transformPerspective: 1100, duration: 0.6, ease: 'power3.out' });
    }
  };
  document.addEventListener('pointermove', onMove, { passive: true });
  return () => document.removeEventListener('pointermove', onMove);
}
