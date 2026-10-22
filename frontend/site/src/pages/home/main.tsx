import { useEffect } from 'react';
import { lookWhile, type Look } from '../../components/FieldCanvas';
import { mount, Shell } from '../../components/Shell';
import { Preloader } from '../../fx/Preloader';
import { Audiences } from './Audiences';
import { Hero } from './Hero';
import { HowItWorks } from './HowItWorks';
import { Proof } from './Proof';
import { Pushback } from './Pushback';
import { DemoBand, ReportTeaser } from './Showcase';
import { Statement, Ticker } from './Ticker';
import { TrustClock } from './TrustClock';
import { FinalCta, Vision } from './Vision';

const dim = (opacity: number) => ({ opacity, morph: 0, speed: 1 });
const HERO: Look = {
  desktop: { x: 2.7, y: -0.1, scale: 0.64, tilt: -0.25, ...dim(1) },
  mobile: { x: 0, y: 1.6, scale: 0.36, tilt: -0.15, ...dim(0.6) },
};
const side = (x: number): Look => ({
  desktop: { x, y: 0.2, scale: 0.9, tilt: -0.7, ...dim(0.34) },
  mobile: { x: 0, y: 0.6, scale: 0.55, tilt: -0.7, ...dim(0.22) },
});

// Where the background scene sits while each section is on screen.
const LOOKS: [string, Look][] = [
  ['top', HERO],
  ['statement', { desktop: { x: 3.6, y: 0, scale: 1.1, tilt: -1.0, ...dim(0.45) }, mobile: { x: 0, y: 0, scale: 0.6, tilt: -0.9, ...dim(0.3) } }],
  ['product-teams', side(-3.8)],
  ['documents', side(3.8)],
  ['support-bots', side(-3.8)],
  ['how', { desktop: { x: 0, y: -2.3, scale: 1.45, tilt: -1.25, ...dim(0.42) }, mobile: { x: 0, y: -1.2, scale: 0.8, tilt: -1.2, ...dim(0.3) } }],
  ['pushback', { desktop: { x: 3.5, y: 0.4, scale: 0.8, tilt: -0.4, opacity: 0.4, morph: 0, speed: -1.6 }, mobile: { x: 0, y: 0.5, scale: 0.5, tilt: -0.4, opacity: 0.25, morph: 0, speed: -1.6 } }],
  ['trust-clock', { desktop: { x: 0, y: 0.1, scale: 1.0, tilt: -0.05, opacity: 0.8, morph: 0, speed: 2.2 }, mobile: { x: 0, y: 0.3, scale: 0.55, tilt: -0.05, opacity: 0.5, morph: 0, speed: 2.2 } }],
  ['proof', side(-3.4)],
  ['report', side(3.6)],
  ['demo-band', side(-3.6)],
  ['vision', { desktop: { x: 2.8, y: -0.1, scale: 1.05, tilt: 0.2, opacity: 1, morph: 1, speed: 1 }, mobile: { x: 0, y: 1.4, scale: 0.6, tilt: 0.2, opacity: 0.7, morph: 1, speed: 1 } }],
  ['start', { desktop: { x: 0, y: -0.6, scale: 1.5, tilt: 0.3, opacity: 0.45, morph: 1, speed: 1 }, mobile: { x: 0, y: 0, scale: 0.8, tilt: 0.3, opacity: 0.3, morph: 1, speed: 1 } }],
];

function Home() {
  useEffect(() => {
    LOOKS.forEach(([id, look]) => {
      const el = document.getElementById(id);
      if (el) lookWhile(el, look);
    });
  }, []);
  return (
    <Shell look={HERO} home>
      <Preloader />
      <Hero />
      <Ticker />
      <Statement />
      <Audiences />
      <HowItWorks />
      <Pushback />
      <TrustClock />
      <Proof />
      <ReportTeaser />
      <DemoBand />
      <Vision />
      <FinalCta />
    </Shell>
  );
}

mount(<Home />);
