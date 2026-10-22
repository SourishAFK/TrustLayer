import { Figure, Sparkline, TrendLine } from '../../components/charts';
import { Cta, Kicker } from '../../fx/fx';
import { withExpectedRange } from '../../lib/trustclock';

// Simulated: % of answers correct per day. A provider update lands on day 27.
const VALUES = [94.1, 94.6, 93.8, 94.3, 94.9, 94.2, 93.7, 94.4, 94.8, 94.0, 94.5, 93.9, 94.6, 94.2, 94.7,
  94.1, 93.6, 94.3, 94.8, 94.4, 93.9, 94.5, 94.2, 94.6, 94.0, 94.3, 86.9, 87.4, 87.1, 87.6];

const DAYS = withExpectedRange(VALUES);

const TILES = [
  { label: '% of answers correct', value: '86.9%', delta: '−7.4 pts since yesterday', alarm: true, spark: VALUES.slice(-12) },
  { label: 'Disagreement across 5 runs', value: '9%', delta: '+6 pts since yesterday', alarm: true, spark: [3, 2, 3, 3, 2, 3, 3, 2, 3, 3, 3, 9] },
  { label: 'Answers changed since yesterday', value: '14', delta: 'usually 1–3', alarm: true, spark: [2, 1, 3, 2, 2, 1, 2, 3, 1, 2, 2, 14] },
  { label: 'Caved under pushback', value: '3 of 20', delta: '+2 since yesterday', alarm: false, spark: [1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 3] },
];

export function TrustClock() {
  return (
    <section id="trust-clock" className="relative py-32 md:py-44">
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <div className="grid gap-10 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <Kicker tone="violet">Trust Clock · in development</Kicker>
            <h2 data-split className="t-display mt-7">Then we keep checking. Every single day.</h2>
          </div>
          <div data-reveal className="space-y-4 self-end text-lg text-ink-2 lg:col-span-5 lg:col-start-8">
            <p>Models update, prompts get edited, policies change. The Trust Clock asks your bot the same 100 questions five times a day and tracks four numbers.</p>
            <p>When one moves more than three times its normal day-to-day wobble, you get an alarm, with the exact answers that changed.</p>
          </div>
        </div>
        <ul className="mt-16 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {TILES.map(t => (
            <li key={t.label} data-reveal data-tilt className={`glass spotlight rounded-2xl p-5 ${t.alarm ? 'beam beam-ember' : ''}`}>
              <div className="text-sm text-ink-2">{t.label}</div>
              <div className="mt-3 text-4xl font-semibold tracking-[-0.03em] text-ink">{t.value}</div>
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5 text-xs text-ink-2">
                  {t.alarm && <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-bad" />}{t.delta}
                </span>
                <Sparkline values={t.spark} alarm={t.alarm} />
              </div>
            </li>
          ))}
        </ul>
        <div data-reveal className="glass mt-3 rounded-3xl p-5 sm:p-8">
          <Figure title="% of answers correct, last 30 days" subtitle="Shaded: the range the Trust Clock expects each day from yesterday’s value and the normal wobble"
            table={{ columns: ['Day', '% correct', 'Expected range', 'Alarm'], rows: DAYS.map(d => [d.day, `${d.value.toFixed(1)}%`, `${d.low.toFixed(1)}–${d.high.toFixed(1)}%`, d.alarm ? 'Yes' : '']) }}
            note="Illustration with simulated data. The Trust Clock is being built now; ask to join the first pilots.">
            <TrendLine days={DAYS} min={84} max={97} />
          </Figure>
        </div>
        <div data-reveal className="mt-10">
          <Cta href="/check/?for=product-teams&from=trust-clock" cursor="Join">Ask to join the pilot</Cta>
        </div>
      </div>
    </section>
  );
}
