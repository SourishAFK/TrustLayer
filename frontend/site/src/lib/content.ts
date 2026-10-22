// Every number on the site comes from one of these sources. Checked October 2026.
export type Source = { title: string; by: string; date: string; url: string };

export const SOURCES = {
  airCanada: {
    title: 'Moffatt v. Air Canada, 2024 BCCRT 149',
    by: 'Civil Resolution Tribunal of British Columbia', date: '14 Feb 2024',
    url: 'https://www.canlii.org/en/bc/bccrt/doc/2024/2024bccrt149/2024bccrt149.html',
  },
  deloitteErrors: {
    title: 'Deloitte to partially refund Australian government for report with apparent AI-generated errors',
    by: 'The Associated Press, via CTV News', date: '7 Oct 2025',
    url: 'https://www.ctvnews.ca/business/article/deloitte-to-partially-refund-australian-government-for-report-with-apparent-ai-generated-errors/',
  },
  deloitteRefund: {
    title: 'Deloitte refunds Australian government over report with AI errors',
    by: 'CFO Dive', date: 'Oct 2025',
    url: 'https://www.cfodive.com/news/deloitte-refunds-60k-report-ai-errors-australian-government-accounting/803321/',
  },
  hallucinationCases: {
    title: 'AI Hallucination Cases database',
    by: 'Damien Charlotin', date: 'as of 16 Oct 2026',
    url: 'https://www.damiencharlotin.com/hallucinations/',
  },
  openaiDeprecations: {
    title: 'Deprecations',
    by: 'OpenAI API documentation', date: 'notice of 14 Oct 2026',
    url: 'https://developers.openai.com/api/docs/deprecations',
  },
  drift: {
    title: "How is ChatGPT's behavior changing over time?",
    by: 'Lingjiao Chen, Matei Zaharia, James Zou (arXiv:2307.09009)', date: '2023',
    url: 'https://arxiv.org/abs/2307.09009',
  },
  rebuttal: {
    title: 'Challenging the Evaluator: LLM Sycophancy Under User Rebuttal',
    by: 'Sungwon Kim, Daniel Khashabi (Findings of EMNLP 2025)', date: '2025',
    url: 'https://arxiv.org/abs/2509.16533',
  },
  benchmark: {
    title: 'TrustLayer verification benchmark: method and results',
    by: 'TrustLayer', date: '17 Oct 2026',
    url: 'https://github.com/SourishAFK/TrustLayer/blob/main/evaluation/verification/README.md',
  },
} satisfies Record<string, Source>;

export type SourceKey = keyof typeof SOURCES;

/** Order sources are numbered in, site-wide. */
export const SOURCE_ORDER: SourceKey[] = [
  'openaiDeprecations', 'drift', 'hallucinationCases', 'deloitteErrors', 'deloitteRefund',
  'airCanada', 'rebuttal', 'benchmark',
];
export const sourceNumber = (key: SourceKey) => SOURCE_ORDER.indexOf(key) + 1;

/** Real, cited incidents for the scrolling ticker. */
export const INCIDENTS: { text: string; when: string; source: SourceKey }[] = [
  { text: 'Air Canada ordered to pay after its chatbot invented a refund rule', when: 'Feb 2024', source: 'airCanada' },
  { text: 'Deloitte refunds more than A$97,000 over a report with a fabricated court quote', when: 'Oct 2025', source: 'deloitteRefund' },
  { text: '2,199 court decisions involving AI-hallucinated content in filings', when: 'as of Oct 2026', source: 'hallucinationCases' },
  { text: 'GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini leave the OpenAI API', when: '14 Jan 2027', source: 'openaiDeprecations' },
  { text: 'GPT-4 on the same prime-number questions: 84% right in March, 51% in June', when: '2023', source: 'drift' },
  { text: 'Llama-3.3-70B took the user’s side 86% of the time after a follow-up rebuttal', when: '2025 study', source: 'rebuttal' },
];

export type Verdict = 'SUPPORTED' | 'CONTRADICTED' | 'DISPUTED' | 'UNVERIFIED' | 'NOT CHECKABLE';

export const VERDICTS: Record<Verdict, { cls: string; label: string; meaning: string }> = {
  SUPPORTED: { cls: 'v-supported', label: 'Supported', meaning: 'A trustworthy source or your own document confirms it, quoted word for word.' },
  CONTRADICTED: { cls: 'v-contradicted', label: 'Contradicted', meaning: 'A trustworthy source, your document, or the math says otherwise. We show the proof and the fix.' },
  DISPUTED: { cls: 'v-disputed', label: 'Disputed', meaning: 'Good sources disagree with each other. We show both sides.' },
  UNVERIFIED: { cls: 'v-unverified', label: 'Unverified', meaning: 'We could not confirm it either way. We never guess, so we say so.' },
  'NOT CHECKABLE': { cls: 'v-not-checkable', label: 'Not checkable', meaning: 'An opinion, advice or prediction. No source can settle it.' },
};

/** Blind held-out run, 17 Oct 2026: evaluation/results/verification_heldout_frozen.json. */
export const BENCHMARK = {
  cases: 24, claims: 103,
  rows: [
    { system: 'TrustLayer, ideal reader', short: 'TrustLayer · ideal reader', ours: true, accuracy: 66.0, falseApprovals: 0, caught: 83.3 },
    { system: 'TrustLayer, noisy reader', short: 'TrustLayer · noisy reader', ours: true, accuracy: 42.7, falseApprovals: 4, caught: 25.0 },
    { system: 'Word-overlap checker (baseline)', short: 'Word-overlap baseline', ours: false, accuracy: 41.7, falseApprovals: 31, caught: 0 },
    { system: 'Claim splitting only (baseline)', short: 'Splitting-only baseline', ours: false, accuracy: 28.2, falseApprovals: 0, caught: 0 },
  ],
  posthoc: { accuracy: 77.7, falseApprovals: 0, caught: 91.7 },
};
