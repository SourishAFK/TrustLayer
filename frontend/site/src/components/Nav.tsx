import { useRef, useState } from 'react';
import { Close, Mark, Menu } from '../fx/icons';
import { Cta } from '../fx/fx';
import { gsap, reducedMotion, ScrollTrigger, useGSAP } from '../lib/motion';

export function Nav({ home = false }: { home?: boolean }) {
  const root = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const at = (hash: string) => (home ? hash : `/${hash}`);
  const links = [
    { href: at('#how'), label: 'How it works' },
    { href: at('#proof'), label: 'Proof' },
    { href: '/demo/', label: 'Live demo' },
    { href: '/report/sample/', label: 'Sample report' },
  ];

  useGSAP(() => {
    const bar = root.current?.querySelector('.bar');
    if (!bar) return;
    if (!reducedMotion()) gsap.from(bar, { y: -40, opacity: 0, duration: 1.4, delay: 0.3 });
    ScrollTrigger.create({
      start: 'top -120',
      onUpdate: self => gsap.to(bar, { yPercent: self.direction === 1 ? -160 : 0, duration: 0.6, overwrite: 'auto' }),
    });
  }, { scope: root });

  useGSAP(() => {
    if (!open || reducedMotion()) return;
    gsap.from('.menu-link', { yPercent: 120, opacity: 0, stagger: 0.07, duration: 1 });
  }, { scope: root, dependencies: [open] });

  return (
    <header ref={root} className="no-print fixed inset-x-0 top-0 z-50 px-4 pt-4">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[80] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-bg">Skip to content</a>
      <nav className="bar glass mx-auto flex h-14 max-w-6xl items-center justify-between rounded-full pl-4 pr-2" aria-label="Main">
        <a href="/" className="flex items-center gap-2.5 font-semibold tracking-tight" data-cursor="Home">
          <Mark size={26} /> <span className="text-[1.05rem]">TrustLayer</span>
        </a>
        <ul className="hidden items-center gap-1 lg:flex">
          {links.map(l => (
            <li key={l.href}>
              <a href={l.href} className="rounded-full px-3.5 py-2 text-[0.92rem] text-ink-2 transition-colors hover:bg-white/5 hover:text-ink">{l.label}</a>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-2">
          <Cta href="/check/?for=general" size="sm" className="hidden sm:inline-flex">Get a free check</Cta>
          <button type="button" className="grid h-10 w-10 place-items-center rounded-full hover:bg-white/5 lg:hidden"
            aria-expanded={open} aria-controls="menu" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen(o => !o)}>
            {open ? <Close className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </nav>
      {open && (
        <div id="menu" className="fixed inset-0 -z-10 flex flex-col justify-end gap-2 bg-bg/95 px-6 pb-14 backdrop-blur-xl lg:hidden">
          {[...links, { href: '/check/?for=general', label: 'Get a free check' }].map(l => (
            <div key={l.href} className="overflow-hidden">
              <a href={l.href} onClick={() => setOpen(false)} className="menu-link t-display block py-1">{l.label}</a>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}
