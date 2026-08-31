---
version: 2.0
name: Apple-Inspired Minimal Design System
description: Minimal, restrained, precise, and premium design language for Email Assistant. Depth and hierarchy achieved through subtle elevation, generous whitespace, weight-driven typography, and purposeful system blue accents.
---

# 🍎 Apple-Inspired Design System Specification

## 1. Core Philosophy

- **Subtlety over Decoration**: Depth comes from barely-perceptible surface elevation (`#161616`) and soft diffuse shadows against true near-black (`#000000`/`#0a0a0a`), never from hard borders or heavy dividers.
- **Restraint**: If a visual element does not convey essential information or enable a direct user action, it is eliminated.
- **Strict Two-Color Text Hierarchy**: Primary text in pure white (`#FFFFFF`), secondary/metadata text in Apple system grey (`#8E8E93`).
- **Single Accent Color Used Sparingly**: Apple System Blue (`#0A84FF`) is reserved strictly for primary interactive actions (Send, active Sync trigger, selected navigation indicator), never for ornamental decoration.
- **Weight Does the Work**: Visual hierarchy is created through typographic weight (`font-semibold` / 600 weight) rather than exaggerated font sizes.
- **Quiet Status Indicators**: Loud badge pills are replaced with minimal inline colored dots (red for urgent, amber for medium, grey for low). Text remains neutral.
- **Generous Whitespace**: Double the internal padding across cards and between layout sections so the interface breathes naturally.
- **Fluid, Precise Motion**: 150–200ms ease transitions on hover, press (`scale(0.98)`), and cross-fading detail selection.

---

## 2. Color Tokens

### Surfaces & Backgrounds
| Token | Hex Value | Purpose |
|---|---|---|
| `bg-canvas` | `#000000` | Canvas base & app background |
| `bg-canvas-subtle` | `#0a0a0a` | Slightly offset panel background (sidebar, list column) |
| `bg-card` | `#161616` | Elevated cards, list items, dialog containers |
| `bg-card-hover` | `#1f1f1f` | Hover state for elevated cards |
| `bg-card-active` | `#262626` | Active / pressed state |
| `bg-input` | `#121212` | Text fields, textareas, search bars |

### Accents & Actions
| Token | Hex Value | Usage Rule |
|---|---|---|
| `accent-primary` | `#0A84FF` | Primary action buttons (Send, Save), active nav selection, active sync state |
| `accent-hover` | `#0077ED` | Hover state on primary buttons |
| `accent-active` | `#0062C4` | Pressed state on primary buttons |
| `accent-subtle` | `rgba(10, 132, 255, 0.12)` | Subtle highlight backdrop for active item |

### Text Hierarchy (Strict 2-Color Rule)
| Token | Hex Value | Purpose |
|---|---|---|
| `text-primary` | `#FFFFFF` | Subject lines, titles, body content, sender names, active labels |
| `text-secondary` | `#8E8E93` | Metadata, timestamps, labels, categories, unselected icons, placeholders |

### Priority & Status Dots
| Priority Level | Dot Color | Value Range | Behavior |
|---|---|---|---|
| **Urgent** | `#FF453A` (System Red) | 9–10 | Small 6px solid circular dot inline with text |
| **Medium** | `#FF9F0A` (System Amber) | 7–8 | Small 6px solid circular dot inline with text |
| **Low / Standard** | `#8E8E93` (System Grey) | 1–6 | Small 6px solid circular dot inline with text |
| **Unread Indicator**| `#0A84FF` (System Blue) | Active Unread | Small 6px circular dot before sender name |

---

## 3. Typography & Hierarchy

### Font Family
```css
font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", Inter, sans-serif;
```

### Scale & Weight Mapping
| Level | Font Size | Weight | Tracking | Line Height | Usage |
|---|---|---|---|---|---|
| **Large Title** | `22px` (`1.375rem`) | `600` (Semibold) | `-0.02em` | `1.3` | View headers, modal titles |
| **Title** | `17px` (`1.0625rem`) | `600` (Semibold) | `-0.015em` | `1.35` | Detail email subject, section titles |
| **Headline** | `14px` (`0.875rem`) | `600` (Semibold) | `-0.01em` | `1.4` | List item subject, sender name |
| **Body** | `14px` (`0.875rem`) | `400` (Regular) | `0em` | `1.55+` | Email body text, chat messages, summary |
| **Subheadline** | `13px` (`0.8125rem`) | `400` (Regular) | `0em` | `1.45` | Snippet previews, form labels |
| **Caption / Meta**| `11px` (`0.6875rem`)| `400` / `500` | `0em` | `1.3` | Timestamps, category names, quiet counters |

---

## 4. Spacing, Elevation & Shadows

### Spacing Rules
- **Card Internal Padding**: `20px` – `28px` (`p-5` to `p-7`), allowing ample internal breathing room.
- **Section Margins & Gaps**: `16px` – `24px` (`gap-4` to `gap-6`).
- **No Visible Borders**: No `border-zinc-800` or `1px solid` outlines between sections. Separation is achieved through background contrast (`#000000` vs `#161616`) and spacing.

### Shadows
```css
/* Subtle soft Apple elevation */
box-shadow: 0 4px 24px rgba(0, 0, 0, 0.45);
```

---

## 5. Motion & Micro-Interactions

1. **Hover & Press Transitions**:
   - `transition: all 180ms cubic-bezier(0.25, 1, 0.5, 1);`
   - Active state press scale: `transform: scale(0.98);`
2. **Detail Cross-Fade**:
   - Switching selected email in the reading pane performs a smooth `180ms` cross-fade opacity transition.
3. **Sync Rotation**:
   - Refresh icon rotates smoothly only when sync is active (`@keyframes apple-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`).

---

## 6. Component Language

### Buttons & Controls
- **Primary Action Buttons**: Fully rounded pill shapes (`rounded-full`), background `#0A84FF`, text `#FFFFFF`, font-weight `600`, subtle press feedback.
- **Secondary Buttons**: Fully rounded pill shapes (`rounded-full`), background `#161616` (or `rgba(255, 255, 255, 0.08)`), text `#FFFFFF` or `#8E8E93`, hover `rgba(255, 255, 255, 0.12)`.
- **Search & Inputs**: Rounded-full or `rounded-2xl` inputs, background `#121212`, text `#FFFFFF`, placeholder `#8E8E93`, minimal focus glow.

### Sidebar
- Clean, minimal, icon-first or single-line layout.
- No decorative emojis, loud "AI" or "RAG" pill badges.
- Clean category labels with quiet numbers in `#8E8E93`.
- Active item marked with clean `#0A84FF` accent or subtle `#161616` pill background.

### Email List & Thread Accordions
- `#161616` clean cards with generous padding (`p-4` to `p-5`).
- Subject line stands out as the loudest visual element in `#FFFFFF` semibold.
- Sender and summary snippet in `#8E8E93`.
- Inline status: small 6px priority dot (`#FF453A`, `#FF9F0A`, or `#8E8E93`) + category name text in `#8E8E93`.

### Detail Reading Pane
- Header: Pure white subject title (`font-semibold`), sender name in `#FFFFFF`, date/time in `#8E8E93`.
- Quick Reply button: Minimal rounded-full secondary pill button.
- **AI Summary Card**: Understated `#161616` surface, quiet "Summary" label in `#8E8E93` (no emoji/fire/sparkle icons), summary text in `#FFFFFF`.
- **Meeting Detection Card**: Subtle `#161616` surface with clean text and rounded-full `.ics` download button.
- **Ghostwriter Hub**: Pill-shaped tone selector chips, clean textarea with `#121212` background, and primary `#0A84FF` pill "Send" button.

### Chat With Inbox (RAG-lite)
- User message bubble: System blue (`#0A84FF`) with white text.
- Assistant message bubble: Soft `#161616` surface with `#FFFFFF` / `#8E8E93` text.
- Prompt chips: Clean pill buttons with neutral grey text (no emojis like 🇵🇰, 🔥, 📅).
- Input bar: Pill-shaped container with inline `#0A84FF` Send button.

### Meetings & Events View
- Minimal grid of `#161616` cards with soft elevation.
- Clean time and location in `#8E8E93`, event title in `#FFFFFF`.
- Pill-shaped `.ics` download button.

---

## 7. Golden Rule of Apple Design
> *"If a visual element doesn't communicate information or enable an action, remove it. Every color, shadow, and animation must justify its existence. When in doubt, simplify further."*
