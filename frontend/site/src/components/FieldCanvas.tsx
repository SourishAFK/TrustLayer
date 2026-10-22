import { useEffect, useRef } from 'react';
import { isDesktop, reducedMotion, ScrollTrigger } from '../lib/motion';
import type { Field, FieldState } from '../three/field';

let field: Field | null = null;
const waiting: ((f: Field) => void)[] = [];

/** Runs `use` once the background scene exists (it loads after first paint, and may never load). */
export function withField(use: (f: Field) => void) {
  if (field) use(field);
  else waiting.push(use);
}

type Preset = Partial<FieldState>;
export type Look = { desktop: Preset; mobile: Preset };

export function applyLook(look: Look) {
  withField(f => {
    Object.assign(f.state, isDesktop() ? look.desktop : look.mobile);
    f.refresh();
  });
}

/** While `section` fills the middle of the screen, the scene glides to `look`. */
export function lookWhile(section: Element, look: Look) {
  withField(() => ScrollTrigger.create({
    trigger: section, start: 'top 55%', end: 'bottom 55%',
    onToggle: self => { if (self.isActive) applyLook(look); },
  }));
}

export function FieldCanvas({ initial }: { initial: Look }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    const start = () => import('../three/field').then(({ createField }) => {
      if (cancelled || !canvas.current) return;
      try {
        const lite = !isDesktop() || (navigator.hardwareConcurrency ?? 8) <= 4;
        field = createField(canvas.current, { reduced: reducedMotion(), lite });
      } catch {
        return; // no WebGL: the CSS backdrop carries the page
      }
      applyLook(initial);
      canvas.current.classList.remove('opacity-0');
      waiting.splice(0).forEach(use => use(field!));
    });
    void start();
    return () => { cancelled = true; field?.dispose(); field = null; };
  }, [initial]);
  return (
    <canvas ref={canvas} aria-hidden="true"
      className="no-print pointer-events-none fixed inset-0 z-0 h-[100lvh] w-full opacity-0 transition-opacity duration-[1.2s]" />
  );
}
