import presets from '../pages/demo/presets.json';
import type { DemoBody } from './api';

export type PresetId = 'answer' | 'document' | 'support';

/** Demo examples (shared with record_demo.py). Each one exercises checks the engine really runs. */
export const PRESETS = presets as Record<PresetId, { name: string; blurb: string; body: DemoBody }>;

export const presetFrom = (search: string): PresetId => {
  const id = new URLSearchParams(search).get('preset');
  return id === 'document' || id === 'support' ? id : 'answer';
};
