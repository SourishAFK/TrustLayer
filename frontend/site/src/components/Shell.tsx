import { StrictMode, useEffect, useRef, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Cursor } from '../fx/Cursor';
import { bindPointerEffects, Grain, ScrollProgress } from '../fx/fx';
import { startAnalytics } from '../lib/analytics';
import { revealWithin, ScrollTrigger, startSmoothScroll, useGSAP } from '../lib/motion';
import '../styles.css';
import { FieldCanvas, type Look } from './FieldCanvas';
import { Footer } from './Footer';
import { Nav } from './Nav';

export function Shell({ children, look, home = false }: { children: ReactNode; look: Look; home?: boolean }) {
  const main = useRef<HTMLElement>(null);
  useEffect(() => bindPointerEffects(), []);
  useGSAP(() => { if (main.current) revealWithin(main.current); }, { scope: main });
  return (
    <>
      <FieldCanvas initial={look} />
      <ScrollProgress />
      <Nav home={home} />
      <main id="main" ref={main} className="relative z-10">{children}</main>
      <Footer />
      <Cursor />
      <Grain />
    </>
  );
}

/** Page entry: smooth scrolling first (the intro pauses it), then React. */
export function mount(page: ReactNode) {
  startSmoothScroll();
  startAnalytics();
  createRoot(document.getElementById('root')!).render(<StrictMode>{page}</StrictMode>);
  document.fonts?.ready.then(() => ScrollTrigger.refresh());
}
