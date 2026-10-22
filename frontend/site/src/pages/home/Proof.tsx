import { Bars, Figure } from '../../components/charts';
import { Aurora, Cite, Counter, Kicker } from '../../fx/fx';
import { BENCHMARK } from '../../lib/content';

const tipFor = (r: (typeof BENCHMARK.rows)[number]) => (
  <><div className="font-medium">{r.system}</div>
    <div className="text-muted">{r.accuracy.toFixed(1)}% of verdicts exactly right · {r.falseApprovals} false approvals</div></>
);

export function Proof() {
  const rows = BENCHMARK.rows;
  return (
    <section id="proof" className="relative py-32 md:py-44">
      <Aurora blobs={[{ c: 'rgb(106 129 242 / 0.14)', x: '50%', y: '0%' }, { c: 'rgb(56 214 255 / 0.07)', x: '-15%', y: '45%' }]} />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <div className="grid gap-10 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <Kicker>Proof, including our misses</Kicker>
            <h2 data-split className="t-display mt-7">We test the checker, and publish where it fails.</h2>
          </div>
          <p data-reveal className="self-end text-lg text-ink-2 lg:col-span-5 lg:col-start-8">
            Before calling anything verified, we ran TrustLayer once on a blind test: {BENCHMARK.cases} cases and{' '}
            {BENCHMARK.claims} claims it had never seen, with the engine frozen.<Cite k="benchmark" />
          </p>
        </div>

        <dl className="mt-16 grid gap-3 md:grid-cols-3">
          {[
            { value: <Counter value={0} />, label: 'false approvals', text: 'With an ideal reader, not one wrong claim was marked "supported".' },
            { value: <Counter value={83} suffix="%" />, label: 'of wrong claims caught', text: 'With an ideal reader. A deliberately noisy reader caught 25%.' },
            { value: <Counter value={31} />, label: 'false approvals by a simple checker', text: 'A word-overlap baseline on the same test approved 31 wrong or unproven claims.' },
          ].map(s => (
            <div key={s.label} data-reveal data-tilt className="glass beam spotlight rounded-3xl p-7">
              <dt className="text-gradient text-[clamp(3rem,6vw,5rem)] font-semibold leading-none tracking-[-0.05em]">{s.value}</dt>
              <dd className="mt-3 font-medium text-ink">{s.label}</dd>
              <dd className="mt-2 text-sm text-ink-2">{s.text}</dd>
            </div>
          ))}
        </dl>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div data-reveal className="glass rounded-3xl p-6 sm:p-8">
            <Figure title="Verdicts exactly right" subtitle={`Blind test, ${BENCHMARK.claims} claims`}
              table={{ columns: ['System', 'Verdicts right', 'False approvals'], rows: rows.map(r => [r.system, `${r.accuracy.toFixed(1)}%`, r.falseApprovals]) }}>
              <Bars rows={rows.map(r => ({ label: r.short, value: r.accuracy, accent: r.ours, tip: tipFor(r) }))} max={100} format={v => `${v.toFixed(1)}%`} />
            </Figure>
          </div>
          <div data-reveal className="glass rounded-3xl p-6 sm:p-8">
            <Figure title="False approvals" subtitle="Wrong or unproven claims marked “supported”. Lower is better."
              table={{ columns: ['System', 'False approvals', 'Verdicts right'], rows: rows.map(r => [r.system, r.falseApprovals, `${r.accuracy.toFixed(1)}%`]) }}
              note="The splitting-only baseline never approves anything, so it also never makes this mistake, and gets far fewer verdicts right.">
              <Bars rows={rows.map(r => ({ label: r.short, value: r.falseApprovals, accent: r.ours, tip: tipFor(r) }))} max={35} format={v => String(v)} />
            </Figure>
          </div>
        </div>

        <details data-reveal className="glass group mt-3 rounded-3xl p-6 sm:p-8">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
            How to read these numbers honestly
            <span className="t-label text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          <ul className="mt-5 grid gap-5 text-ink-2 md:grid-cols-3">
            <li><b className="font-medium text-ink">Who wrote the test.</b> Separate AI authors that never saw our code wrote the cases. A person has not yet reviewed their answer labels. The sources are saved web pages, so every run sees the same internet.</li>
            <li><b className="font-medium text-ink">What “ideal reader” means.</b> The part that reads a source passage was swapped for the right answer, to measure everything else: search, checks and verdict rules. Real AI readers make mistakes, so we also show a deliberately noisy one.</li>
            <li><b className="font-medium text-ink">Once, then fixed.</b> We ran the blind test once. After studying its failures we fixed them, and the same test now scores {BENCHMARK.posthoc.accuracy}% with {BENCHMARK.posthoc.falseApprovals} false approvals, but that number is no longer blind. A fresh blind test is next.</li>
          </ul>
        </details>
      </div>
    </section>
  );
}
