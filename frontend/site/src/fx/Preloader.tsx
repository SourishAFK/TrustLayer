import { useRef, useState } from 'react';
import { getLenis, gsap, reducedMotion, useGSAP } from '../lib/motion';

let resolveIntro = () => {};
/** Resolves when the intro curtain starts lifting (or at once when there is no intro). */
export const introDone = new Promise<void>(resolve => { resolveIntro = resolve; });

/** First visit per session: the Trust Clock "calibrates", then the curtain splits open. */
export function Preloader() {
  const [show] = useState(() => {
    if (reducedMotion()) return false;
    try { return !sessionStorage.getItem('tl-intro'); } catch { return true; }
  });
  const root = useRef<HTMLDivElement>(null);
  const count = useRef<HTMLSpanElement>(null);

  useGSAP(() => {
    if (!show) { resolveIntro(); return; }
    try { sessionStorage.setItem('tl-intro', '1'); } catch { /* private mode */ }
    getLenis()?.stop();
    const counter = { n: 0 };
    const q = gsap.utils.selector(root);
    gsap.timeline({
      onComplete: () => { getLenis()?.start(); if (root.current) root.current.style.display = 'none'; },
    })
      .from(q('.arc'), { drawSVG: '0%', duration: 1.35, ease: 'power2.inOut' }, 0)
      .from(q('.tick'), { drawSVG: '0%', duration: 0.5, ease: 'power2.out' }, 1.0)
      .to(counter, { n: 100, duration: 1.35, ease: 'power2.inOut', onUpdate: () => {
        if (count.current) count.current.textContent = String(Math.round(counter.n)).padStart(3, '0');
      } }, 0)
      .from(q('.word'), { duration: 1.1, scrambleText: { text: '', chars: 'upperCase', speed: 0.5 } }, 0.05)
      .add(resolveIntro, 1.45)
      .to(q('.center'), { opacity: 0, scale: 0.92, filter: 'blur(8px)', duration: 0.45, ease: 'power2.in' }, 1.45)
      .to(q('.half-top'), { yPercent: -100, duration: 1.05, ease: 'expo.inOut' }, 1.55)
      .to(q('.half-bottom'), { yPercent: 100, duration: 1.05, ease: 'expo.inOut' }, 1.55)
      .to(q('.seam'), { scaleX: 1, duration: 0.5, ease: 'expo.out' }, 1.3)
      .to(q('.seam'), { opacity: 0, duration: 0.4 }, 1.75);
  }, { scope: root });

  if (!show) return null;
  return (
    <div ref={root} aria-hidden="true" className="no-print fixed inset-0 z-[100]">
      <div className="half-top absolute inset-x-0 top-0 h-1/2 bg-bg" />
      <div className="half-bottom absolute inset-x-0 bottom-0 h-1/2 bg-bg" />
      <div className="seam absolute inset-x-0 top-1/2 h-px origin-center scale-x-0 bg-[linear-gradient(90deg,transparent,#38d6ff,#8b5cff,transparent)] shadow-[0_0_24px_#38d6ff]" />
      <div className="center absolute inset-0 flex flex-col items-center justify-center gap-7">
        <svg width="120" height="120" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="22" fill="none" stroke="rgb(255 255 255 / .1)" strokeWidth="2.5" />
          <circle className="arc" cx="32" cy="32" r="22" fill="none" stroke="#38d6ff" strokeWidth="2.5" strokeLinecap="round"
            transform="rotate(-90 32 32)" style={{ filter: 'drop-shadow(0 0 6px #38d6ff)' }} />
          <path className="tick" d="M23.5 32.5l6 6 11-12" fill="none" stroke="#f2f3f7" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className="flex items-baseline gap-4 font-mono text-sm text-ink-2">
          <span ref={count} className="text-2xl tabular-nums text-ink">000</span>
          <span className="word t-label">Calibrating the Trust Clock</span>
        </div>
      </div>
    </div>
  );
}
