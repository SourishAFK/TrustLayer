// Adapted from React Bits SpotlightCard's pointer-position radial fill technique.
// Original copyright (c) 2026 David Haz. See THIRD_PARTY_NOTICES.md.
// Simplified for a static, accessible report panel with no animation loop.
import { useRef, type PropsWithChildren } from 'react';

export default function SpotlightCard({ children, className = '' }: PropsWithChildren<{ className?: string }>) {
  const root = useRef<HTMLDivElement>(null);
  return <div ref={root} className={`spotlight-card ${className}`} onPointerMove={event => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const card = root.current;
    if (!card) return;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--pointer-x', `${event.clientX - rect.left}px`);
    card.style.setProperty('--pointer-y', `${event.clientY - rect.top}px`);
  }}><span className="spotlight-fill" aria-hidden="true" />{children}</div>;
}
