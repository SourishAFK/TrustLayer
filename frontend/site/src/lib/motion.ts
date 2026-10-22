import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin';
import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';
import Lenis from 'lenis';

gsap.registerPlugin(ScrollTrigger, SplitText, ScrambleTextPlugin, DrawSVGPlugin, useGSAP);
gsap.defaults({ ease: 'expo.out', duration: 1.1 });

export const reducedMotion = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
export const finePointer = () => typeof matchMedia === 'function' && matchMedia('(pointer: fine)').matches;
export const isDesktop = () => typeof matchMedia === 'function' && matchMedia('(min-width: 1024px)').matches;

let lenis: Lenis | null = null;

/** Smooth scrolling driven by GSAP's ticker so ScrollTrigger and Lenis share one clock. */
export function startSmoothScroll() {
  if (lenis || reducedMotion()) return lenis;
  lenis = new Lenis({ duration: 1.2, easing: t => Math.min(1, 1.001 - 2 ** (-10 * t)), anchors: { offset: -80 } });
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add(time => lenis?.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
  return lenis;
}

export const getLenis = () => lenis;

/** Scroll-in reveals for every [data-split] heading and [data-reveal] block inside `root`. */
export function revealWithin(root: HTMLElement) {
  if (reducedMotion()) return;
  root.querySelectorAll<HTMLElement>('[data-split]').forEach(el => {
    SplitText.create(el, {
      type: 'lines,words', mask: 'lines', autoSplit: true,
      onSplit: self => gsap.from(self.words, {
        yPercent: 115, rotate: 4, opacity: 0, stagger: 0.045, duration: 1.3,
        scrollTrigger: { trigger: el, start: 'top 88%', once: true },
      }),
    });
  });
  const blocks = root.querySelectorAll<HTMLElement>('[data-reveal]');
  if (blocks.length) {
    gsap.set(blocks, { y: 34, opacity: 0, filter: 'blur(10px)' });
    ScrollTrigger.batch(blocks, {
      start: 'top 90%', once: true,
      onEnter: batch => gsap.to(batch, { y: 0, opacity: 1, filter: 'blur(0px)', stagger: 0.08, duration: 1.2, overwrite: true }),
    });
  }
  root.querySelectorAll<HTMLElement>('[data-speed]').forEach(el => {
    gsap.to(el, { yPercent: -Number(el.dataset.speed) * 100, ease: 'none',
      scrollTrigger: { trigger: el, start: 'top bottom', end: 'bottom top', scrub: true } });
  });
}

/**
 * Sticky scrollytelling. Desktop: the timeline follows the scroll through `section`.
 * Small screens: it plays once when `visual` arrives. Reduced motion: the end state, still.
 */
export function scrollStory(section: Element, visual: Element, build: () => gsap.core.Timeline) {
  gsap.matchMedia().add({ desktop: '(min-width: 1024px)', reduce: '(prefers-reduced-motion: reduce)' }, ctx => {
    const tl = build();
    if (ctx.conditions?.reduce) { tl.progress(1).pause(); return; }
    if (ctx.conditions?.desktop) {
      ScrollTrigger.create({ trigger: section, start: 'top 35%', end: 'bottom 85%', scrub: 0.8, animation: tl });
    } else {
      tl.pause(0);
      ScrollTrigger.create({ trigger: visual, start: 'top 75%', once: true, onEnter: () => { tl.play(); } });
    }
  });
}

export { gsap, ScrollTrigger, SplitText, useGSAP };
