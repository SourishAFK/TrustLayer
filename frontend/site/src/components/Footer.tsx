import { useRef } from 'react';
import { ArrowUpRight, Mark } from '../fx/icons';
import { analyticsOn } from '../lib/analytics';
import { SOURCE_ORDER, SOURCES } from '../lib/content';

const COLUMNS = [
  { title: 'Try it', links: [
    { href: '/demo/', label: 'Live demo' }, { href: '/report/sample/', label: 'Sample report' },
    { href: '/check/?for=general', label: 'Get a free check' },
  ] },
  { title: 'For', links: [
    { href: '/check/?for=product-teams', label: 'AI product teams' },
    { href: '/check/?for=documents', label: 'AI-written documents' },
    { href: '/check/?for=support-bots', label: 'Customer-support bots' },
  ] },
];

export function Footer() {
  const word = useRef<HTMLDivElement>(null);
  const onMove = (e: React.PointerEvent) => {
    const r = word.current?.getBoundingClientRect();
    if (!r || !word.current) return;
    word.current.style.setProperty('--wx', `${e.clientX - r.left}px`);
    word.current.style.setProperty('--wy', `${e.clientY - r.top}px`);
  };
  return (
    <footer className="no-print relative z-10 mt-32 overflow-hidden border-t border-line bg-bg/80 backdrop-blur-sm">
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-20 md:grid-cols-12">
        <div className="md:col-span-4">
          <a href="/" className="flex items-center gap-2.5 text-lg font-semibold"><Mark size={30} /> TrustLayer</a>
          <p className="mt-5 max-w-xs text-ink-2">Catch your AI's mistakes before your customers, clients or a judge do.</p>
          <p className="mt-6 max-w-xs text-sm text-muted">
            TrustLayer shows evidence. It does not certify that an AI is compliant or approved by any regulator, and it is not legal advice.
          </p>
        </div>
        {COLUMNS.map(col => (
          <div key={col.title} className="md:col-span-2">
            <h2 className="t-label text-muted">{col.title}</h2>
            <ul className="mt-5 space-y-3">
              {col.links.map(l => <li key={l.href}><a className="underline-grow text-ink-2 hover:text-ink" href={l.href}>{l.label}</a></li>)}
            </ul>
          </div>
        ))}
        <div id="sources" className="md:col-span-4">
          <h2 className="t-label text-muted">Sources</h2>
          <ol className="mt-5 space-y-2.5 text-sm">
            {SOURCE_ORDER.map((key, i) => {
              const s = SOURCES[key];
              return (
                <li key={key} className="flex gap-3">
                  <span className="font-mono text-cyan">[{i + 1}]</span>
                  <a href={s.url} target="_blank" rel="noreferrer" className="group text-ink-2 hover:text-ink">
                    {s.title} <span className="text-muted">— {s.by}, {s.date}</span>
                    <ArrowUpRight className="ml-1 inline h-3 w-3 opacity-50 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                  </a>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
      <div ref={word} onPointerMove={onMove} aria-hidden="true"
        className="relative select-none px-4 pb-6 text-center font-semibold leading-[0.8] tracking-[-0.06em] text-transparent [font-size:clamp(4rem,19vw,17rem)] [background-image:linear-gradient(180deg,rgb(255_255_255/0.11),rgb(255_255_255/0.015))] [-webkit-background-clip:text] [background-clip:text]">
        TrustLayer
        <span className="pointer-events-none absolute inset-0 px-4 pb-6 text-transparent [-webkit-background-clip:text] [background-clip:text] [background-image:radial-gradient(240px_circle_at_var(--wx,50%)_var(--wy,50%),#a5f3ff,#38d6ff_35%,transparent_70%)]">TrustLayer</span>
      </div>
      <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-4 px-6 pb-10 text-xs text-muted">
        <span>© 2026 TrustLayer</span>
        <span>Every number on this site links to its source.{analyticsOn && ' We count visits with Plausible, which uses no cookies.'}</span>
      </div>
    </footer>
  );
}
