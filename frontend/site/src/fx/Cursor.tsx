import { useEffect, useRef, useState } from 'react';
import { finePointer, gsap, reducedMotion } from '../lib/motion';

/** Dot + lagging ring. Grows over links; shows a label over [data-cursor="Label"]. Mouse only. */
export function Cursor() {
  const [on] = useState(() => finePointer() && !reducedMotion());
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  const [label, setLabel] = useState('');

  useEffect(() => {
    if (!on || !dot.current || !ring.current) return;
    document.documentElement.classList.add('has-cursor');
    const dx = gsap.quickTo(dot.current, 'x', { duration: 0.12, ease: 'power3' });
    const dy = gsap.quickTo(dot.current, 'y', { duration: 0.12, ease: 'power3' });
    const rx = gsap.quickTo(ring.current, 'x', { duration: 0.5, ease: 'power3' });
    const ry = gsap.quickTo(ring.current, 'y', { duration: 0.5, ease: 'power3' });
    let mode = '', text = '', seen = false;
    gsap.set([dot.current, ring.current], { opacity: 0 });
    const set = (next: string, nextText = '') => {
      if (next === mode && nextText === text) return;
      mode = next;
      text = nextText;
      setLabel(nextText);
      gsap.to(ring.current, {
        scale: next === 'label' ? 2.4 : next === 'link' ? 1.7 : next === 'text' ? 0 : 1,
        backgroundColor: next === 'label' ? 'rgba(242,243,247,0.95)' : next === 'link' ? 'rgba(56,214,255,0.12)' : 'rgba(0,0,0,0)',
        duration: 0.45, ease: 'expo.out',
      });
      gsap.to(dot.current, { scale: next === 'label' || next === 'text' ? 0 : 1, duration: 0.3 });
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return;
      if (!seen) {
        seen = true;
        gsap.set([dot.current, ring.current], { x: e.clientX, y: e.clientY });
        gsap.to([dot.current, ring.current], { opacity: 1, duration: 0.4 });
      }
      dx(e.clientX); dy(e.clientY); rx(e.clientX); ry(e.clientY);
      const el = e.target as Element | null;
      const labelled = el?.closest<HTMLElement>('[data-cursor]');
      if (el?.closest('input, textarea, select, [contenteditable]')) set('text');
      else if (labelled?.dataset.cursor) set('label', labelled.dataset.cursor);
      else if (el?.closest('a, button, label, [role="button"], summary')) set('link');
      else set('');
    };
    const hide = () => gsap.to([dot.current, ring.current], { opacity: 0, duration: 0.3 });
    const show = () => gsap.to([dot.current, ring.current], { opacity: 1, duration: 0.3 });
    window.addEventListener('pointermove', move, { passive: true });
    document.addEventListener('pointerleave', hide);
    document.addEventListener('pointerenter', show);
    return () => {
      document.documentElement.classList.remove('has-cursor');
      window.removeEventListener('pointermove', move);
      document.removeEventListener('pointerleave', hide);
      document.removeEventListener('pointerenter', show);
    };
  }, [on]);

  if (!on) return null;
  return (
    <div aria-hidden="true" className="no-print pointer-events-none fixed inset-0 z-[90]">
      <div ref={ring} className="absolute left-0 top-0 -ml-5 -mt-5 flex h-10 w-10 items-center justify-center rounded-full border border-white/40">
        <span className="t-label scale-[0.42] whitespace-nowrap font-semibold text-bg">{label}</span>
      </div>
      <div ref={dot} className="absolute left-0 top-0 -ml-[3px] -mt-[3px] h-1.5 w-1.5 rounded-full bg-white mix-blend-difference" />
    </div>
  );
}
