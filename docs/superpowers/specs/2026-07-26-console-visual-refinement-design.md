# Console Visual Refinement Design

## Goal

Improve the console's readability and visual consistency without changing its functions, data flow, navigation, or workflow behavior.

The chosen direction is a restrained technology aesthetic:

- dark sidebar and light content area;
- moderate spacing and information density;
- blue-violet accents, fine borders, and small status indicators;
- short, subtle interaction motion.

## Scope

Use the existing HTML, JavaScript, and CSS. Prefer CSS-only changes and add markup classes only where an existing selector cannot express the design safely.

Included:

- navigation, page headers, cards, forms, buttons, tables, logs, tags, and empty states;
- consistent spacing, typography, borders, radii, shadows, and focus states;
- hover, press, reveal, and page-transition feedback;
- desktop and narrow-screen layouts.

Excluded:

- new pages, controls, workflows, or data;
- changes to navigation order or user actions;
- UI frameworks, icon libraries, animation libraries, particle effects, and glassmorphism;
- decorative motion that runs continuously.

## Visual System

### Layout

Keep the current application structure. Use a deep blue-black sidebar to anchor navigation and a soft gray-white canvas for reading. Place primary content on white surfaces with restrained borders instead of heavy shadows.

Spacing should remain moderate: enough separation to scan sections without reducing useful information on screen.

### Color

Use a small token set:

- deep blue-black for navigation;
- soft gray-white for the application canvas;
- white for primary surfaces;
- blue-violet for active navigation, primary actions, focus, and progress;
- muted slate for secondary text;
- existing semantic green, amber, and red for success, warning, and destructive states.

Do not use accent gradients on large backgrounds. A subtle gradient is allowed on the main action button and active navigation marker.

### Components

- **Navigation:** active item receives a blue-violet edge marker, faint tinted background, and clear text contrast.
- **Cards:** consistent border, radius, padding, title spacing, and optional hover lift only when the card is interactive.
- **Buttons:** one dominant primary style, a quiet secondary style, and an explicit destructive style. Press feedback uses a small scale change.
- **Forms:** shared field height, border, label rhythm, focus ring, disabled state, and validation state.
- **Tables and logs:** improve row separation, alignment, code readability, and sticky context where already supported.
- **Statuses:** pair concise labels with small colored dots; never rely on color alone.
- **Learning materials:** retain readable Chinese sections and version states, using the same surface and heading hierarchy as project materials.

## Motion

Interaction motion lasts 150–200 ms with standard ease-out timing:

- navigation and button state transitions;
- interactive card lift of no more than two pixels;
- collapsible content reveal;
- lightweight page content fade and vertical settle.

Motion must not delay input, hide content, or change layout unexpectedly. Under `prefers-reduced-motion: reduce`, remove non-essential animation and transforms.

## Responsive and Accessibility Requirements

- Preserve the existing mobile breakpoint behavior and prevent horizontal overflow.
- Maintain visible keyboard focus for all interactive elements.
- Keep text and control contrast readable on both sidebar and content surfaces.
- Do not communicate run state or errors through color alone.
- Keep minimum practical click and tap targets on narrow screens.

## Implementation Boundaries

The shortest safe implementation is preferred:

1. consolidate visual tokens in the existing stylesheet;
2. normalize shared components through existing selectors;
3. add only the few classes required to distinguish interactive and static cards;
4. avoid JavaScript changes unless an existing rendering template lacks a stable class hook.

No backend, API, storage, workflow, or model-routing code should change.

## Verification

- Run the existing console-focused tests.
- Run the complete test suite because static rendering assertions are shared with other workflows.
- Check the main pages at desktop width and approximately 390 px.
- Verify keyboard focus, reduced-motion behavior, overflow, empty states, loading states, long labels, and error messages.
- Confirm that the browser console has no errors and that all existing actions still reach the same handlers.

## Acceptance Criteria

- Every existing feature remains available through the same operation path.
- Sidebar, content surfaces, forms, buttons, tables, logs, and statuses use one coherent visual system.
- The interface remains comfortable for long-form Chinese reading.
- Motion is subtle, responsive, and disabled when reduced motion is requested.
- No new runtime dependency is added.
- Existing automated tests pass, and desktop and narrow-screen visual checks reveal no clipping or unusable controls.
