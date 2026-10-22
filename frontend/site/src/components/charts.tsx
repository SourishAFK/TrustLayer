import { useEffect, useRef, useState, type ReactNode } from 'react';
import { gsap, reducedMotion, useGSAP } from '../lib/motion';
import type { Day } from '../lib/trustclock';

// Chart marks follow the dataviz spec: bars <= 24px with a 4px rounded data end, 2px lines,
// >= 8px markers with a 2px surface ring, hairline grid, text in ink (never the data color).
export const SERIES = '#6a81f2';   // TrustLayer; validated with the alarm red in dark and light mode
export const QUIET = '#4a5163';    // baselines and context
export const ALARM = '#d43126';

type Tip = { x: number; y: number; body: ReactNode } | null;

function useTip() {
  const box = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip>(null);
  const at = (x: number, y: number, body: ReactNode) => setTip({ x, y, body });
  const fromEvent = (e: React.PointerEvent | React.FocusEvent, body: ReactNode) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const t = (e.target as Element).getBoundingClientRect();
    const x = 'clientX' in e ? e.clientX : t.left + t.width / 2;
    const y = 'clientY' in e ? e.clientY : t.top;
    at(x - r.left, y - r.top, body);
  };
  const node = tip && (
    <div role="tooltip" className="pointer-events-none absolute z-20 w-max max-w-64 -translate-x-1/2 -translate-y-[calc(100%+14px)] rounded-xl border border-line-2 bg-surface-2/95 px-3 py-2 text-xs leading-relaxed text-ink shadow-2xl backdrop-blur"
      style={{ left: tip.x, top: tip.y }}>
      {tip.body}
    </div>
  );
  return { box, at, fromEvent, hide: () => setTip(null), node };
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width: width || 640, ready: width > 0 };
}

export type Table = { columns: string[]; rows: (string | number)[][] };

/** A chart with a title, a table view, and an optional note. */
export function Figure({ title, subtitle, note, table, children, light = false }: {
  title: string; subtitle?: string; note?: ReactNode; table: Table; children: ReactNode; light?: boolean;
}) {
  const [asTable, setAsTable] = useState(false);
  const ink = light ? 'text-paper-ink' : 'text-ink';
  const muted = light ? 'text-[#5d6270]' : 'text-muted';
  return (
    <figure className="relative">
      <figcaption className="mb-5 flex items-start justify-between gap-4">
        <div>
          <div className={`font-medium ${ink}`}>{title}</div>
          {subtitle && <div className={`mt-1 text-sm ${muted}`}>{subtitle}</div>}
        </div>
        <button type="button" onClick={() => setAsTable(v => !v)} aria-pressed={asTable}
          className={`t-label shrink-0 rounded-full border px-3 py-1.5 ${light ? 'border-black/15 text-[#3c404a] hover:bg-black/5' : 'border-line-2 text-ink-2 hover:bg-white/5'}`}>
          {asTable ? 'Show chart' : 'Show table'}
        </button>
      </figcaption>
      {asTable ? (
        <div className="overflow-x-auto">
          <table className={`w-full text-left text-sm tabular-nums ${ink}`}>
            <thead><tr>{table.columns.map(c => <th key={c} className={`border-b py-2 pr-4 font-medium ${light ? 'border-black/10' : 'border-line'} ${muted}`}>{c}</th>)}</tr></thead>
            <tbody>{table.rows.map((row, i) => (
              <tr key={i}>{row.map((cell, j) => <td key={j} className={`border-b py-2 pr-4 ${light ? 'border-black/5' : 'border-line'}`}>{cell}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>
      ) : children}
      {note && <div className={`mt-4 text-xs leading-relaxed ${muted}`}>{note}</div>}
    </figure>
  );
}

/** Horizontal bars from one baseline; the value sits at the tip. */
export function Bars({ rows, max, format }: {
  rows: { label: string; value: number; accent?: boolean; tip: ReactNode }[];
  max: number; format: (v: number) => string;
}) {
  const tip = useTip();
  useGSAP(() => {
    if (reducedMotion()) return;
    gsap.from('.bar-fill', { scaleX: 0, duration: 1.6, stagger: 0.12, ease: 'expo.out',
      scrollTrigger: { trigger: tip.box.current, start: 'top 85%', once: true } });
  }, { scope: tip.box });
  return (
    <div ref={tip.box} className="relative space-y-4" onPointerLeave={tip.hide}>
      {rows.map(row => (
        <div key={row.label} className="grid grid-cols-[minmax(7rem,38%)_1fr] items-center gap-4">
          <div className={`text-sm ${row.accent ? 'text-ink' : 'text-ink-2'}`}>{row.label}</div>
          <div tabIndex={0} aria-label={`${row.label}: ${format(row.value)}`}
            onPointerMove={e => tip.fromEvent(e, row.tip)} onFocus={e => tip.fromEvent(e, row.tip)} onBlur={tip.hide}
            className="flex h-8 items-center gap-3 rounded outline-none focus-visible:ring-2 focus-visible:ring-cyan/60">
            <div className="bar-fill h-[18px] origin-left rounded-r-[4px]"
              style={{ width: `${Math.max(row.value / max * 100, 0.6)}%`, background: row.accent ? SERIES : QUIET, boxShadow: row.accent ? `0 0 24px -6px ${SERIES}` : undefined }} />
            <span className="shrink-0 text-sm font-medium text-ink">{format(row.value)}</span>
          </div>
        </div>
      ))}
      {tip.node}
    </div>
  );
}


/** One series over time, its expected range as a 10% wash, crosshair tooltip, alarm markers. */
export function TrendLine({ days, min, max, unit = '%' }: { days: Day[]; min: number; max: number; unit?: string }) {
  const { ref, width, ready } = useWidth();
  const tip = useTip();
  const [hover, setHover] = useState<number | null>(null);
  const height = 260, pad = { l: 44, r: 16, t: 16, b: 30 };
  const x = (d: number) => pad.l + ((d - days[0].day) / (days[days.length - 1].day - days[0].day)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - min) / (max - min)) * (height - pad.t - pad.b);
  const line = days.map((d, i) => `${i ? 'L' : 'M'}${x(d.day).toFixed(1)},${y(d.value).toFixed(1)}`).join('');
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  const band = [...days.map(d => `${x(d.day)},${y(clamp(d.high))}`), ...[...days].reverse().map(d => `${x(d.day)},${y(clamp(d.low))}`)].join(' ');
  const ticks = [min, min + (max - min) / 3, min + (2 * (max - min)) / 3, max].map(v => Math.round(v));
  const path = useRef<SVGPathElement>(null);
  useGSAP(() => {
    const el = path.current;
    if (!el || !ready || reducedMotion()) return;
    gsap.from(el, {
      drawSVG: '0%', duration: 2.4, ease: 'power2.inOut',
      scrollTrigger: { trigger: el, start: 'top 85%', once: true },
      onComplete: () => { el.style.removeProperty('stroke-dasharray'); el.style.removeProperty('stroke-dashoffset'); },
    });
  }, { dependencies: [ready] });
  const pick = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    const px = clientX - r.left;
    let best = 0;
    days.forEach((d, i) => { if (Math.abs(x(d.day) - px) < Math.abs(x(days[best].day) - px)) best = i; });
    return best;
  };
  const show = (i: number) => {
    const d = days[i];
    setHover(i);
    tip.at(x(d.day), y(d.value), (
      <><div className="font-medium">Day {d.day} · {d.value.toFixed(1)}{unit} correct</div>
        <div className="text-muted">Expected {d.low.toFixed(1)}–{d.high.toFixed(1)}{unit}</div>
        {d.alarm && <div className="mt-1 text-ink">⚠ {d.alarm}</div>}</>
    ));
  };
  return (
    <div ref={tip.box} className="relative">
      <div ref={ref} tabIndex={0} aria-label="Line chart; use the arrow keys to step through the days."
        className="relative outline-none focus-visible:ring-2 focus-visible:ring-cyan/60"
        onPointerMove={e => show(pick(e.clientX))} onPointerLeave={() => { setHover(null); tip.hide(); }}
        onKeyDown={e => {
          if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
          e.preventDefault();
          show(Math.min(days.length - 1, Math.max(0, (hover ?? days.length - 1) + (e.key === 'ArrowRight' ? 1 : -1))));
        }}
        onBlur={() => { setHover(null); tip.hide(); }}>
        <svg width={width} height={height} className="block overflow-visible" aria-hidden="true">
          {ticks.map(t => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="rgb(255 255 255 / .07)" />
              <text x={pad.l - 10} y={y(t) + 4} textAnchor="end" className="fill-muted text-[12px] tabular-nums">{t}{unit}</text>
            </g>
          ))}
          {[days[0], days[Math.floor(days.length / 2)], days[days.length - 1]].map(d => (
            <text key={d.day} x={x(d.day)} y={height - 8} textAnchor="middle" className="fill-muted text-[12px]">Day {d.day}</text>
          ))}
          <polygon points={band} fill={SERIES} opacity={0.1} />
          <path ref={path} d={line} fill="none" stroke={SERIES} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 6px ${SERIES})` }} />
          {hover !== null && <line x1={x(days[hover].day)} x2={x(days[hover].day)} y1={pad.t} y2={height - pad.b} stroke="rgb(255 255 255 / .25)" />}
          {days.map((d, i) => (d.alarm || i === hover) && (
            <circle key={d.day} cx={x(d.day)} cy={y(d.value)} r={5} fill={d.alarm ? ALARM : SERIES} stroke="#0b0d12" strokeWidth={2} />
          ))}
          {days.filter(d => d.alarm).map(d => (
            <g key={`a${d.day}`}>
              <circle cx={x(d.day)} cy={y(d.value)} r={12} fill="none" stroke={ALARM} opacity={0.5} className="pulse-dot" style={{ transformOrigin: `${x(d.day)}px ${y(d.value)}px` }} />
              <text x={x(d.day) - 14} y={y(d.value) + 4} textAnchor="end" className="fill-ink text-[12px] font-medium">Alarm</text>
            </g>
          ))}
        </svg>
      </div>
      {tip.node}
    </div>
  );
}

/** Small trend line for stat tiles: context in the quiet hue, the latest point in the accent. */
export function Sparkline({ values, alarm = false }: { values: number[]; alarm?: boolean }) {
  const w = 120, h = 32, lo = Math.min(...values), hi = Math.max(...values);
  const pt = (v: number, i: number) => [(i / (values.length - 1)) * (w - 6) + 3, h - 4 - ((v - lo) / (hi - lo || 1)) * (h - 8)];
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${pt(v, i).join(',')}`).join('');
  const [lx, ly] = pt(values[values.length - 1], values.length - 1);
  return (
    <svg width={w} height={h} aria-hidden="true" className="overflow-visible">
      <path d={d} fill="none" stroke={QUIET} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r={4} fill={alarm ? ALARM : SERIES} stroke="#0b0d12" strokeWidth={2} />
    </svg>
  );
}

/** Part-to-whole in one bar, 2px surface gaps between segments, legend underneath. */
export function StackBar({ parts, surface = '#0b0d12', light = false }: {
  parts: { label: string; value: number; color: string; tip: ReactNode }[]; surface?: string; light?: boolean;
}) {
  const tip = useTip();
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  return (
    <div ref={tip.box} className="relative" onPointerLeave={tip.hide}>
      <div className="flex h-6 w-full gap-[2px] overflow-hidden rounded-[4px]" style={{ background: surface }}>
        {parts.filter(p => p.value > 0).map(p => (
          <div key={p.label} tabIndex={0} aria-label={`${p.label}: ${p.value} of ${total}`}
            onPointerMove={e => tip.fromEvent(e, p.tip)} onFocus={e => tip.fromEvent(e, p.tip)} onBlur={tip.hide}
            className="h-full outline-none focus-visible:opacity-80" style={{ width: `${(p.value / total) * 100}%`, background: p.color }} />
        ))}
      </div>
      <ul className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {parts.map(p => (
          <li key={p.label} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color }} />
            <span className={light ? 'text-paper-ink' : 'text-ink'}>{p.label}</span>
            <span className={`tabular-nums ${light ? 'text-[#5d6270]' : 'text-muted'}`}>{p.value}</span>
          </li>
        ))}
      </ul>
      {tip.node}
    </div>
  );
}
