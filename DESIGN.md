---
version: "alpha"
name: "PaperFlow Design Layout"
description: "Paperflow Design Pricing Section is designed for comparing plans and supporting conversion decisions. Key features include plan comparison blocks and conversion-oriented actions. It is suitable for subscription pricing pages and plan comparison experiences."
colors:
  primary: "#E65C00"
  secondary: "#FFB380"
  tertiary: "#FFF5E6"
  neutral: "#78716C"
  background: "#E65C00"
  surface: "#FDFBF7"
  text-primary: "#78716C"
  text-secondary: "#292524"
  border: "#E7E5E4"
  accent: "#E65C00"
typography:
  display-lg:
    fontFamily: "Inter"
    fontSize: "51px"
    fontWeight: 500
    lineHeight: "51px"
    letterSpacing: "-0.025em"
  body-md:
    fontFamily: "Inter"
    fontSize: "12.75px"
    fontWeight: 400
    lineHeight: "17px"
  label-md:
    fontFamily: "Inter"
    fontSize: "12.75px"
    fontWeight: 500
    lineHeight: "17px"
rounded:
  full: "9999px"
spacing:
  base: "4.25px"
  sm: "4.25px"
  md: "6.38px"
  lg: "8.5px"
  xl: "12.75px"
  gap: "4.25px"
  card-padding: "8.5px"
  section-padding: "25.5px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    typography: "{typography.label-md}"
    rounded: "{rounded.full}"
    padding: "6.38px"
  card:
    rounded: "17px"
    padding: "25.5px"
---

## Overview

- **Composition cues:**
  - Layout: Grid
  - Content Width: Full Bleed
  - Framing: Glassy
  - Grid: Strong

## Colors

The color system uses light mode with #E65C00 as the main accent and #78716C as the neutral foundation.

- **Primary (#E65C00):** Main accent and emphasis color.
- **Secondary (#FFB380):** Supporting accent for secondary emphasis.
- **Tertiary (#FFF5E6):** Reserved accent for supporting contrast moments.
- **Neutral (#78716C):** Neutral foundation for backgrounds, surfaces, and supporting chrome.

- **Usage:** Background: #E65C00; Surface: #FDFBF7; Text Primary: #78716C; Text Secondary: #292524; Border: #E7E5E4; Accent: #E65C00

- **Gradients:** bg-gradient-to-b from-[#FDFBF7] to-[#F7F4EB], bg-gradient-to-b from-[#FCFAF6]/90 to-[#F5F2EA]/90, bg-gradient-to-br from-[#F5EFE6] to-[#FCE8D5], bg-gradient-to-tr from-[#F4EBE1] to-[#FCEEE3]

## Typography

Typography relies on Inter across display, body, and utility text.

- **Display (`display-lg`):** Inter, 51px, weight 500, line-height 51px, letter-spacing -0.025em.
- **Body (`body-md`):** Inter, 12.75px, weight 400, line-height 17px.
- **Labels (`label-md`):** Inter, 12.75px, weight 500, line-height 17px.

## Layout

Layout follows a grid composition with reusable spacing tokens. Preserve the grid, full bleed structural frame before changing ornament or component styling. Use 4.25px as the base rhythm and let larger gaps step up from that cadence instead of introducing unrelated spacing values.

Treat the page as a grid / full bleed composition, and keep that framing stable when adding or remixing sections.

- **Layout type:** Grid
- **Content width:** Full Bleed
- **Base unit:** 4.25px
- **Scale:** 4.25px, 6.38px, 8.5px, 12.75px, 17px, 25.5px, 34px, 51px
- **Section padding:** 25.5px, 34px
- **Card padding:** 8.5px, 12.75px, 25.5px, 34px
- **Gaps:** 4.25px, 6.38px, 8.5px, 12.75px

## Elevation & Depth

Depth is communicated through glass, border contrast, and reusable shadow or blur treatments. Keep those recipes consistent across hero panels, cards, and controls so the page reads as one material system.

Surfaces should read as glass first, with borders, shadows, and blur only reinforcing that material choice.

- **Surface style:** Glass
- **Borders:** 1px #E7E5E4; 16px #F2DECE; 12px #FFFFFF; 1px #FFFFFF
- **Shadows:** rgba(255, 255, 255, 0.8) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.02) 0px 4px 20px 0px; rgb(255, 255, 255) 0px 0px 0px 0px, rgba(255, 255, 255, 0.6) 0px 0px 0px 1px, rgba(230, 92, 0, 0.03) 0px 8px 40px 0px, rgba(0, 0, 0, 0.02) 0px 1px 3px 0px; rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(230, 92, 0, 0.2) 0px 2px 10px 0px
- **Blur:** 64px

### Techniques
- **Gradient border shell:** Use a thin gradient border shell around the main card. Wrap the surface in an outer shell with 4.25px padding and a 17px radius. Drive the shell with linear-gradient(rgb(253, 251, 247), rgb(247, 244, 235)) so the edge reads like premium depth instead of a flat stroke. Keep the actual stroke understated so the gradient shell remains the hero edge treatment. Inset the real content surface inside the wrapper with a slightly smaller radius so the gradient only appears as a hairline frame.

## Shapes

Shapes rely on a tight radius system anchored by 8.5px and scaled across cards, buttons, and supporting surfaces. Icon geometry should stay compatible with that soft-to-controlled silhouette.

Use the radius family intentionally: larger surfaces can open up, but controls and badges should stay within the same rounded DNA instead of inventing sharper or pill-only exceptions.

- **Corner radii:** 8.5px, 17px, 42.5px, 9999px
- **Icon treatment:** Linear
- **Icon sets:** Solar

## Components

Anchor interactions to the detected button styles. Reuse the existing card surface recipe for content blocks.

### Buttons
- **Primary:** background #E65C00, text #FFFFFF, radius 9999px, padding 6.38px, border 0px solid rgb(229, 231, 235).

### Cards and Surfaces
- **Card surface:** border 0px solid rgb(229, 231, 235), radius 17px, padding 25.5px, shadow rgba(255, 255, 255, 0.8) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.02) 0px 4px 20px 0px.
- **Card surface:** border 0px solid rgb(229, 231, 235), radius 0px, padding 25.5px, shadow none.
- **Card surface:** radius 0px, padding 25.5px, shadow none.

### Iconography
- **Treatment:** Linear.
- **Sets:** Solar.

## Do's and Don'ts

Use these constraints to keep future generations aligned with the current system instead of drifting into adjacent styles.

### Do
- Do use the primary palette as the main accent for emphasis and action states.
- Do keep spacing aligned to the detected 4.25px rhythm.
- Do reuse the Glass surface treatment consistently across cards and controls.
- Do keep corner radii within the detected 8.5px, 17px, 42.5px, 9999px family.

### Don't
- Don't introduce extra accent colors outside the core palette roles unless the page needs a new semantic state.
- Don't mix unrelated shadow or blur recipes that break the current depth system.
- Don't exceed the detected expressive motion intensity without a deliberate reason.

## Motion

Motion feels expressive but remains focused on interface, text, and layout transitions. Timing clusters around 150ms and 500ms. Easing favors ease and 0. Hover behavior focuses on text and shadow changes. Scroll choreography uses GSAP ScrollTrigger for section reveals and pacing.

**Motion Level:** expressive

**Durations:** 150ms, 500ms, 300ms

**Easings:** ease, 0, 0.2, 1), cubic-bezier(0.4, cubic-bezier(0

**Hover Patterns:** text, shadow, color, stroke

**Scroll Patterns:** gsap-scrolltrigger
