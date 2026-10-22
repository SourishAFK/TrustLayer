import type { SVGProps } from 'react';
import type { Verdict } from '../lib/content';

type P = SVGProps<SVGSVGElement>;
const base = { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const;

export const Check = (p: P) => <svg {...base} {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
export const Cross = (p: P) => <svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>;
export const Question = (p: P) => <svg {...base} {...p}><path d="M9.2 9a3 3 0 1 1 4.3 2.7c-.9.4-1.5 1.1-1.5 2.1v.4" /><path d="M12 18h.01" /></svg>;
export const Split = (p: P) => <svg {...base} {...p}><path d="M12 4v6M12 10l-6 8M12 10l6 8" /></svg>;
export const Dash = (p: P) => <svg {...base} {...p}><path d="M6 12h12" /></svg>;
export const Arrow = (p: P) => <svg {...base} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
export const ArrowUpRight = (p: P) => <svg {...base} {...p}><path d="M7 17L17 7M8 7h9v9" /></svg>;
export const Alert = (p: P) => <svg {...base} {...p}><path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17h.01" /></svg>;
export const Menu = (p: P) => <svg {...base} {...p}><path d="M4 8h16M4 16h16" /></svg>;
export const Close = (p: P) => <svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>;
export const Print = (p: P) => <svg {...base} {...p}><path d="M7 9V4h10v5M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2" /><path d="M7 14h10v6H7z" /></svg>;
export const Loop = (p: P) => <svg {...base} {...p}><path d="M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5" /></svg>;

export const VERDICT_ICON: Record<Verdict, (p: P) => React.JSX.Element> = {
  SUPPORTED: Check, CONTRADICTED: Cross, DISPUTED: Split, UNVERIFIED: Question, 'NOT CHECKABLE': Dash,
};

/** The TrustLayer mark: a clock ring with its checking arc and a tick. */
export function Mark({ size = 28, className = '', light = false }: { size?: number; className?: string; light?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="mark-arc" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a5f3ff" /><stop offset="1" stopColor="#8b5cff" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="22" fill="none" stroke={light ? 'rgb(0 0 0 / .14)' : 'rgb(255 255 255 / .16)'} strokeWidth="5" />
      <path d="M32 10a22 22 0 0 1 21 15.3" fill="none" stroke="url(#mark-arc)" strokeWidth="5" strokeLinecap="round" />
      <path d="M23.5 32.5l6 6 11-12" fill="none" stroke={light ? '#14161c' : '#f2f3f7'} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
