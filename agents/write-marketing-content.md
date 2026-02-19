# Marketing Content Style Guide

This guide establishes the voice, structure, and formatting standards for Salable marketing content—blog posts, announcements, case studies, and documentation. The principles here draw from the Chicago Manual of Style (18th Edition), along with guidance from Google, Microsoft, and Apple style guides, and Nielsen Norman Group research on how people actually read online.

The core philosophy is simple: write prose that guides readers through ideas with narrative flow. Lists and tables have their place, but they should support your argument, not replace it.

## Voice and Tone

Write like you're explaining something to a smart colleague over coffee. Your tone should feel warm and conversational without tipping into casualness that undermines credibility. You're confident in what Salable does, but never arrogant about it.

Use the second person throughout—address readers directly as "you" rather than hiding behind passive constructions or the distant "one." Contractions like "you'll," "we're," and "it's" make your writing feel human. If a sentence sounds stiff when you read it aloud, rewrite it until it flows naturally.

Active voice keeps your writing crisp and direct. Compare "The subscription was created by the API" with "The API created the subscription." The second version is shorter, clearer, and assigns responsibility unambiguously. Passive voice occasionally serves a purpose—when the actor is unknown or deliberately de-emphasized—but treat it as an exception rather than a default.

Avoid hedging language that weakens your message. Phrases like "it's important to note that" or "it should be mentioned that" add nothing. If something matters, state it directly.

## Content Structure and Hierarchy

Research from Nielsen Norman Group shows that 79% of web users scan rather than read word-by-word. This doesn't mean you should fragment everything into bullet points—it means you should structure your prose to reward both scanners and readers.

### The Inverted Pyramid

Lead with your conclusion or the key benefit. Don't make readers wade through background before reaching the point. The first sentence of every piece—and ideally every paragraph—should carry the most important information. Supporting details, context, and caveats follow.

This structure serves scanners who only read headings and opening lines while giving thorough readers a clear framework to build on. It also makes your content more shareable, since the opening can often stand alone as a summary.

### The Story Spine for Longer Pieces

For blog posts, case studies, and feature announcements, narrative structure transforms dry information into engaging content. The story spine framework moves through five stages: setup, problem, struggle, solution, and resolution.

The setup establishes the world your reader lives in—what they're trying to accomplish, what tools they're using, what success looks like. The problem introduces the obstacle or pain point that disrupts this world. The struggle acknowledges that this problem isn't trivial; it shows you understand the real challenges involved. The solution presents your approach (whether that's a Salable feature or a broader strategy). The resolution paints the picture of life after the solution—concrete outcomes and benefits.

This framework works because readers connect emotionally with narrative. Lists provide information, but stories create understanding and memory.

### Heading Hierarchy

Every piece has exactly one H1—the title. H2 headings divide major sections, and H3 headings subdivide those sections when necessary. Don't skip levels; an H3 should always follow an H2, not appear directly under H1.

Keep headings concise and descriptive. A reader scanning only your headings should understand the shape of your argument. "Why Per-Seat Licensing Fails at Scale" tells readers more than "The Problem" or "Issues to Consider."

## When to Use Prose, Lists, and Tables

Lists and tables are tools with specific purposes. Using them carelessly makes all your content look the same and strips away the connections between ideas. You can't make an argument with bullets alone—prose provides the connective tissue that guides readers through your reasoning.

### Prose Belongs in Most Places

Use flowing paragraphs for arguments and explanations, persuasive content, cause-and-effect relationships, and any storytelling. When you need to show why something matters, how ideas connect, or what readers should conclude, prose is your medium.

Prose is more persuasive than lists because it guides readers through your logic step by step. Bullet points present items as equals; prose lets you emphasize, qualify, and build momentum toward a conclusion.

### Lists Serve Specific Purposes

Use bulleted lists for truly discrete, parallel items—things that don't require explanation and genuinely belong in the same category. Sequential steps that must be followed in order work well as numbered lists. Quick reference material (API parameters, configuration options) suits list format when readers will return repeatedly to scan for specific items.

Limit lists to five to seven items. Beyond that, you're probably combining categories that deserve separate treatment or burying important distinctions in a wall of bullets. When you have three or fewer items, embed them in prose instead: "Salable handles metering, billing, and entitlements so you can focus on your product."

Every item in a list should follow parallel grammatical structure. If your first bullet starts with a verb, every bullet should start with a verb. If your first bullet is a noun phrase, keep them all as noun phrases.

### Avoiding List Fatigue

Never stack lists back-to-back. Two consecutive bullet sections create a rhythm that scanners start to skim past entirely. If you find yourself with multiple lists in sequence, step back and consider whether prose would serve better—or whether your sections need reorganization.

Avoid paragraph-length bullet points. If an item needs multiple sentences of explanation, it shouldn't be a bullet. Write a short section with a heading instead.

Watch for bullets that strip important context. "Reduces churn" as a bullet point loses the power of "By making subscription changes self-service, Salable reduces churn—customers who can easily downgrade during tight months will upgrade again when circumstances improve, rather than canceling entirely."

### Tables Require Genuine Tabular Data

Tables belong only where you have true row-column relationships—where data intersects across two dimensions in meaningful ways. Pricing comparison tables can work when comparing multiple plans across multiple features. Feature matrices can work when readers need to cross-reference specific capabilities.

Never use tables as glorified lists. If you're comparing two items on one dimension, use prose: "The Starter plan includes 1,000 API calls per month; the Pro plan includes unlimited calls." If you're listing features without comparison, use prose or a short list.

Tables are scanning aids, not persuasion tools. They help readers find specific facts, but they don't help readers understand why those facts matter.

## Formatting Standards

These guidelines follow the Chicago Manual of Style, adapted for digital content.

### Title Case for Headings

Capitalize the first and last words always. Capitalize all nouns, verbs, adjectives, adverbs, and pronouns. Lowercase articles (the, a, an), short prepositions (to, of, for, in, on), and coordinating conjunctions (and, but, or, nor, yet, so). Capitalize prepositions of five or more letters: About, Against, Between, Through, Without.

Examples of correct title case: "How to Integrate Salable with Your Application," "Everything You Need to Know About Per-Seat Licensing," "Why We Built This and What It Means for You."

### The Serial Comma

Always use the Oxford comma in lists of three or more items. Write "metering, billing, and entitlements," not "metering, billing and entitlements." The serial comma prevents ambiguity and costs nothing.

### Colons and Capitalization

Capitalize the first word after a colon only when a complete sentence follows. "The integration offers three benefits: speed, reliability, and simplicity" keeps lowercase because what follows isn't a sentence. "The answer surprised us: Every customer we interviewed had the same complaint" capitalizes because a full sentence follows.

### Possessives

Form possessives by adding 's even to names ending in s. Write "Salable's API," "Stripe's webhooks," "James's configuration." The only exception is ancient classical names (Socrates' philosophy, Achilles' heel), which won't appear in our content.

### Emphasis and Formatting

Use bold sparingly—for key terms on first use or critical warnings. When everything is bold, nothing is. Use italics for emphasis within prose, publication titles, and when introducing technical terms. Never combine bold and italic on the same text.

Format inline code with single backticks: `subscription_id`. Use fenced code blocks for examples spanning multiple lines. Code formatting signals "type this exactly" to readers.

Write descriptive link text that makes sense out of context. Readers scanning may see only your links, and screen readers often navigate by links alone. "Learn more about usage-based pricing" works; "click here" does not.

## Common Anti-Patterns

Learning what to avoid is as valuable as learning what to do. These patterns weaken content even when the underlying information is sound.

Consecutive bullet sections create list fatigue. Readers' eyes glaze over, and important distinctions get lost. If you've written two bulleted lists in a row, stop and restructure.

Paragraph-length bullets defeat the purpose of listing. If a point needs substantial explanation, it deserves prose treatment with its own heading.

Tables as glorified lists waste the power of tabular format and make simple information harder to scan. If your "table" has only one meaningful column, it's not a table.

Walls of unbroken text overwhelm readers, but the solution isn't fragmenting into bullets—it's adding appropriate headings and paragraph breaks while keeping the narrative flow.

Over-formatting undermines readability. When sentences contain bold and italic and code formatting and links, readers can't tell what actually matters. Choose one emphasis per sentence maximum.

Starting sentences with "This" without a clear antecedent forces readers to look backward to understand what you mean. "This approach" or "This configuration" clarifies the reference.

## Transforming Over-Listed Content

The following examples show how to convert bullet-heavy drafts into engaging prose while preserving all the information.

### Before: List Overload

> **Why Choose Salable?**
>
> - Easy integration
> - Flexible pricing models
> - Usage-based billing
> - Self-service portals
> - Automatic tax calculation
> - Webhook notifications
> - Detailed analytics
> - Multi-currency support

### After: Narrative Prose

> **Why Choose Salable?**
>
> Salable handles the entire billing and subscription lifecycle so you can focus on building your product. Integration takes hours rather than weeks because our API follows predictable patterns and our SDKs handle the complexity of metered billing, usage tracking, and entitlement enforcement.
>
> You get the flexibility to experiment with pricing—flat subscriptions, per-seat licensing, usage-based tiers, or hybrid models—without rewriting your billing logic each time. Your customers get self-service portals where they can manage their own subscriptions, reducing your support burden while improving their experience.
>
> Everything runs on infrastructure designed for real businesses: automatic tax calculation across jurisdictions, multi-currency support for global sales, webhook notifications for every billing event, and analytics that show you what's actually driving revenue. The system scales with you, handling enterprise customers as easily as startups.

The rewritten version carries the same information but explains _why_ each capability matters and how they connect. Readers understand not just what Salable does, but what it means for them.

### Before: Disconnected Steps

> **Getting Started**
>
> 1. Create an account
> 2. Set up your product
> 3. Configure pricing
> 4. Add the SDK
> 5. Test the integration
> 6. Go live

### After: Guided Narrative

> **Getting Started**
>
> Start by creating your Salable account and defining your product—the thing you're selling. This takes about five minutes and establishes the foundation for everything that follows.
>
> Next, configure your pricing model. You might start simple with a flat monthly subscription, or jump straight into per-seat licensing or usage-based billing. Salable supports changing models later, so don't over-plan; choose what fits your current customers.
>
> With your product and pricing configured, add our SDK to your application. The SDK handles authentication, entitlement checking, and usage reporting. Our quickstart guide walks through each integration point with code samples in your language of choice.
>
> Before launching, run through our testing checklist to verify that subscriptions flow correctly, usage meters accurately, and webhooks fire as expected. Our sandbox environment lets you simulate the entire customer lifecycle without touching real payment methods.
>
> When everything checks out, flip the switch to production. Your billing infrastructure is live.

The narrative version guides readers through _why_ each step matters and _how_ it connects to what comes next. The numbered list provided sequence but no understanding.

## Applying These Principles

This guide itself aims to follow its own advice. You'll notice it uses prose for explanations, limits lists to contexts where they genuinely help, and leads each section with its core point before elaborating.

As you write, keep asking: Am I guiding the reader through an argument, or just presenting disconnected points? Does this list genuinely help, or am I defaulting to bullets because they're easier to write? Would a first-time reader understand not just what we offer, but why it matters to them?

Great content marketing doesn't just inform—it persuades. And persuasion happens through narrative, not lists.
