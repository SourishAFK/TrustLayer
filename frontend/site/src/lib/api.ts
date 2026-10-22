// Talks to the TrustLayer API. Same origin by default; set VITE_API_BASE when the site and the
// API are deployed separately (and list the site in the API's TRUSTLAYER_CORS_ORIGINS).
export const API_BASE = String(import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '');

export const AUDIENCES = ['product-teams', 'documents', 'support-bots', 'general'] as const;
export type Audience = (typeof AUDIENCES)[number];

export function audienceFrom(search: string): Audience {
  const value = new URLSearchParams(search).get('for');
  return (AUDIENCES as readonly string[]).includes(value ?? '') ? (value as Audience) : 'general';
}

const UTM = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];
const clip = (text: string) => text.slice(0, 300);

/** Where a sign-up came from: campaign tags, the page (with its ?for= tag) and the referring site. */
export function leadSource(url: URL, referrer: string): Record<string, string> {
  const source: Record<string, string> = { page: clip(url.pathname + url.search) };
  for (const key of UTM) {
    const value = url.searchParams.get(key);
    if (value) source[key] = clip(value);
  }
  if (referrer) {
    try {
      const ref = new URL(referrer);
      if (ref.host !== url.host) source.referrer = clip(ref.origin + ref.pathname);
    } catch { /* not a URL: ignore */ }
  }
  return source;
}

export type LeadForm = {
  audience: Audience; name: string; email: string; company: string; role: string;
  message: string; link: string; consent: boolean; website: string; would_pay: '' | WouldPay;
};

export type WouldPay = 'no' | 'up-to-50' | '50-200' | '200-plus';
export const WOULD_PAY: { value: WouldPay; label: string }[] = [
  { value: 'no', label: 'No, just curious' }, { value: 'up-to-50', label: 'Up to $50' },
  { value: '50-200', label: '$50–200' }, { value: '200-plus', label: '$200+' },
];

/** Where to write when the sign-up form cannot reach us. Set VITE_CONTACT_EMAIL at build time. */
export const CONTACT_EMAIL = String(import.meta.env.VITE_CONTACT_EMAIL ?? '').trim();

/** The sign-up as plain text, for an email or the clipboard when the form cannot be sent. */
export function leadSummary(form: LeadForm, audienceLabel: string) {
  return [
    `Name: ${form.name}`, `Email: ${form.email}`, `Company: ${form.company}`, `Role: ${form.role}`,
    `Check for: ${audienceLabel}`,
    `Would pay for a full check: ${WOULD_PAY.find(p => p.value === form.would_pay)?.label ?? 'not answered'}`,
    `Link: ${form.link}`, '', 'What should we check?', form.message,
  ].join('\n');
}

export type SendResult = { ok: true } | { ok: false; message: string };

export async function sendLead(form: LeadForm, source: Record<string, string>): Promise<SendResult> {
  try {
    const response = await fetch(`${API_BASE}/v1/leads`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, would_pay: form.would_pay || undefined, source }),
    });
    if (response.ok) return { ok: true };
    return { ok: false, message: leadError(response.status) };
  } catch {
    return { ok: false, message: 'We could not reach our server. Check your connection and try again.' };
  }
}

export function leadError(status: number) {
  if (status === 422) return 'Some details look off. Check your email address and any link, then try again.';
  if (status === 429) return 'Too many sign-ups from your network just now. Please try again in an hour.';
  return 'Our sign-up inbox is having a moment. Please try again in a few minutes.';
}

/** Yields one parsed object per line of a newline-delimited JSON stream. */
export async function* readNdjson(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split('\n');
    buffer = done ? '' : lines.pop() ?? '';
    for (const line of lines) if (line.trim()) yield JSON.parse(line);
    if (done) return;
  }
}

export type DemoBody = {
  response_text: string;
  original_question?: string;
  answer_key?: { name: string; text: string };
};

// Phrases, not sentences: the demo page finishes them ("…, so here's a recorded run").
const DEMO_PAUSED: Record<number, string> = {
  404: 'Live checks are paused',
  422: 'The demo takes up to 3,000 characters of answer and 6,000 of policy text',
  429: "Live checks have reached today's limit",
};
export const UNREACHABLE = "We couldn't reach the live checker";

export class DemoUnavailable extends Error {
  constructor(public status: number) {
    super(DEMO_PAUSED[status] ?? UNREACHABLE);
  }
}

export async function openDemoStream(body: DemoBody, signal: AbortSignal) {
  const response = await fetch(`${API_BASE}/v1/demo/verify/stream`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  if (!response.ok || !response.body) throw new DemoUnavailable(response.status);
  return readNdjson(response.body);
}
