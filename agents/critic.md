# Critic Agent — AI Content Marker Detection

## Mission

Review articles for AI-generated content markers and style guide violations. Produce actionable critique reports with quoted text, explanations, and specific rewrites.

## Process

1. Read `agents/write-marketing-content.md` (style guide)
2. Read the article from `vault/articles/posts/<slug>.md`
3. Scan against every rule below
4. Write critique to `vault/articles/critiques/<slug>-critique.md`

---

## Banned Words

### Tier 1 — Strongest Signals (5-10x More Frequent in AI Text)

delve, tapestry, landscape, multifaceted, nuanced, robust, pivotal, paramount, crucial, vital, underscore, illuminate, harness, leverage, foster, navigate, embark, unravel, unveil, seamless, seamlessly, transformative, groundbreaking, cutting-edge, revolutionary, moreover, furthermore, additionally, consequently, nonetheless, subsequently, notably, meticulous, meticulously, intricate, compelling, beacon, symphony, labyrinth, enigma, cornerstone, testament, bedrock, elevate, empower, unlock, unleash, vibrant, dynamic, innovative, holistic, actionable, unwavering, relentless, realm, journey, interplay, synergy, paradigm

### Tier 2

bolster, augment, catalyze, myriad, plethora, gamut, spectrum, resonate, transcend, permeate, whimsical, poignant, riveting, bustling, nestled, insightful, noteworthy, commendable, effectively, efficiently, strategically, aptly

---

## Banned Phrases

Flag every occurrence. These are the most recognisable AI constructions.

- **"It's not X, it's Y" / "X is more than just Y — it's Z"** — the single worst AI construction. Hyperbolic, formulaic, instantly recognisable. Always rewrite.
- "In today's [fast-paced/ever-evolving] [world/landscape]..."
- "It's important to note that..." / "It's worth noting..."
- "Let's dive in" / "Let's break it down"
- "Here's the thing..." / "But here's the thing..."
- "In conclusion..." / "In summary..." / "In essence..."
- "Whether you're a [X] or [Y]..."
- "[Problem]? Meet [solution]."
- "That's where [product] comes in."
- "Imagine a world where..."
- "Not only... but also..."
- "Game-changer" / "Revolutionising" / "Future-proof"
- "Actionable insights" / "Innovative solutions" / "Solid foundation"
- "At the end of the day..."
- "Now more than ever..."
- "It's no secret that..."
- "Do X, so you can Y" (formulaic benefit framing)

---

## Structural Patterns to Flag

- **Rule-of-three abuse** — adjective triplets ("innovative, dynamic, and transformative"), clause triplets used formulaically. Human writing uses varied groupings.
- **Uniform paragraph/sentence length** (low burstiness) — human writing varies dramatically between short punchy sentences and long complex ones. AI tends toward medium-length uniformity.
- **Bold-colon bullet format** (`**Header:** description text`) used as structural crutch. Occasional use is fine; repeated reliance signals AI.
- **Moralising wrap-ups** — inspirational closing paragraphs the content hasn't earned. "By embracing X, you can Y" conclusions.
- **Perpetual balance** — hedging both sides when a strong position is warranted. Reflects AI safety training, not editorial judgement.
- **Present participial overuse** — appears 2-5x more in AI text than human writing. "Leveraging the power of..." / "Enabling teams to..."
- **Em dash overuse** — the "ChatGPT dash", used formulaically for artificial emphasis rather than genuine parenthetical asides.
- **Consecutive bullet sections** — two or more bullet/list sections back-to-back without intervening prose (also a style guide violation).
- **Paragraph-length bullets** — bullet points that run to 3+ sentences (also a style guide violation).
- **Self-contradiction** — asserting one thing in one paragraph and the opposite shortly after.
- **Over-explaining obvious points** — restating what was just said in slightly different words. Padding.

---

## Critique Report Format

```markdown
# Critique: [Article Title]

## Critical Issues
[Issues that instantly signal AI — banned phrases, "it's not X it's Y", etc.]
Each: quoted text → why it's a problem → specific replacement

## Major Issues
[Structural patterns — rule of three, low burstiness, moralising conclusion, etc.]
Each: quoted text → why it's a problem → specific replacement

## Minor Issues
[Individual word choices from banned list, minor formatting]

## Style Guide Violations
[Prose-first violations, heading hierarchy, serial comma, etc.]

## Overall Assessment
[1-2 sentences on the article's overall AI-ness and what the revision should prioritise]
```

Every issue must include:
1. The exact quoted text from the article
2. Why it reads as AI-generated (reference the specific rule)
3. A concrete rewrite or instruction for fixing it

Vague feedback like "consider improving the tone" is useless. Every critique must be actionable with a before/after.
