// Cookie-free visit counting with Plausible: no cookies, no personal data, so no consent banner.
// Off unless VITE_ANALYTICS_DOMAIN is set at build time (the domain as registered in Plausible).
const DOMAIN = String(import.meta.env.VITE_ANALYTICS_DOMAIN ?? '').trim();
export const analyticsOn = Boolean(DOMAIN);

type Options = { props?: Record<string, string>; callback?: () => void };
type Plausible = ((event: string, options?: Options) => void) & { q?: unknown[][] };
declare global { interface Window { plausible?: Plausible } }

/** Scroll-depth marks newly passed (25, 50, 75, 100% of the page seen). */
export function depthMarks(seenBottom: number, pageHeight: number, sent: ReadonlySet<number>): number[] {
  const seen = pageHeight > 0 ? (seenBottom / pageHeight) * 100 : 0;
  return [25, 50, 75, 100].filter(mark => seen >= mark - 0.5 && !sent.has(mark));
}

export function startAnalytics() {
  if (!DOMAIN) return;
  // Queue calls made before the script arrives; Plausible replays the queue when it loads.
  window.plausible ??= Object.assign((...args: unknown[]) => { (window.plausible!.q ??= []).push(args); }, {});
  const script = document.createElement('script');
  script.defer = true;
  script.dataset.domain = DOMAIN;
  script.src = 'https://plausible.io/js/script.js';
  document.head.appendChild(script);

  const sent = new Set<number>();
  let pending = false;
  window.addEventListener('scroll', () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      for (const mark of depthMarks(window.scrollY + window.innerHeight, document.documentElement.scrollHeight, sent)) {
        sent.add(mark);
        window.plausible?.('Scroll depth', { props: { depth: String(mark), page: location.pathname } });
      }
    });
  }, { passive: true });

  // Links marked data-track="Event name" (with data-audience / data-place) count their clicks.
  document.addEventListener('click', event => {
    const link = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[data-track]');
    if (!link) return;
    const props = { audience: link.dataset.audience ?? '', place: link.dataset.place ?? '', page: location.pathname };
    const sameTab = event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && link.target !== '_blank';
    if (!sameTab) { window.plausible?.(link.dataset.track!, { props }); return; }
    // Leaving the page can cancel the request, so wait for it, but never more than 400ms.
    event.preventDefault();
    let gone = false;
    const go = () => { if (!gone) { gone = true; location.assign(link.href); } };
    window.plausible?.(link.dataset.track!, { props, callback: go });
    setTimeout(go, 400);
  }, true);
}
