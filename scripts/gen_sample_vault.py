"""Regenerate samples/vault. Usage (repo root): python3 scripts/gen_sample_vault.py .
import base64
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "samples" / "vault"

N = {}  # path -> (frontmatter tags list or None, title, body)


def note(path, tags, body, extra_fm=""):
    N[path] = (tags, extra_fm, body.strip() + "\n")


# ---------------- Product pricing ----------------
note("product/pricing/Pricing Strategy.md", ["pricing", "strategy"], """
# Pricing Strategy

Our pricing has to do two jobs: make the first purchase easy and make expansion feel fair.
We currently sell three tiers and a usage add-on. See [[Tier Design]] for the packaging logic
and [[Value Metric]] for why we charge per active seat instead of per workspace.

## Principles

- Price on value delivered, not on cost to serve. #value-based
- Keep the entry tier below the credit-card approval threshold most managers have (~$500/yr).
- Never punish adoption: heavy users should feel rewarded, not taxed.

## Open questions

Do we discount annual plans by 15% or 20%? The [[Discounting Policy]] note argues for 15%.
How should churned accounts be won back? The [[Churn Analysis 2026]] data suggests that price
is rarely the stated reason, but onboarding friction often is (see [[Onboarding Friction Themes]]).
Compare with the competitor work in [[Competitor Teardown Q3]].
""")

note("product/pricing/Tier Design.md", ["pricing", "packaging"], """
# Tier Design

Three tiers: **Starter**, **Team**, **Business**. Each tier boundary should map to a moment
where the customer's job changes, not to an arbitrary feature list.

## Starter
Single team, up to 10 seats, core graph and search. Goal: zero-friction self-serve.

## Team
SSO-lite, shared views, priority support. This is where the [[Value Metric]] starts to matter.

## Business
Audit log, SAML, data residency. Sold with a human; the price page says "talk to us".

The tier fences were tested in the [[Van Westendorp Survey]]: willingness to pay drops sharply
above $24 per seat per month for Team. #willingness-to-pay
""")

note("product/pricing/Value Metric.md", ["pricing"], """
# Value Metric

A value metric is the unit you charge for. Good ones grow with the value the customer gets,
are easy to predict, and are easy to measure on our side.

Candidates we considered:

| Metric | Grows with value | Predictable | Measurable |
| --- | --- | --- | --- |
| Seats | medium | high | high |
| Active seats | high | medium | high |
| Documents indexed | high | low | high |
| Queries | high | low | medium |

We chose **active seats** (a seat that logged in during the billing month). It keeps the
[[Pricing Strategy]] promise of never punishing adoption, because inactive seats are free.
Related: [[Usage-Based Add-On]].
""")

note("product/pricing/Usage-Based Add-On.md", ["pricing", "usage"], """
# Usage-Based Add-On

Some customers index huge archives. Rather than a fourth tier, we sell an add-on: every
10,000 documents above the tier allowance costs a flat monthly fee.

Why an add-on and not pure usage pricing? Finance teams hate unpredictable bills. A stepped
add-on keeps the invoice boring. This mirrors what we learned in [[Churn Analysis 2026]]:
bill shock was the #2 reason for downgrades among accounts larger than 200 seats.

See also [[Value Metric|our value metric]] and the overall [[Pricing Strategy]].
""")

note("product/pricing/Discounting Policy.md", ["pricing", "sales"], """
# Discounting Policy

Discounts are a tool, not a habit. Rules for the sales team:

1. Annual prepay: 15% off list. No stacking with other discounts.
2. Nonprofits and education: 40% off Team, case by case for Business.
3. Multi-year: an extra 5% per year, capped at 25% total.
4. Anything beyond that needs approval from the pricing council.

The 15% annual figure comes from the [[Van Westendorp Survey]] follow-up: customers barely
reacted to the difference between 15% and 20%, so the extra 5% was pure margin loss.
#discounts #sales-playbook
""")

note("product/pricing/Van Westendorp Survey.md", ["pricing", "research"], """
# Van Westendorp Survey

We ran the four classic questions (too cheap, cheap, expensive, too expensive) on 412
respondents from our trial cohort.

## Results

- Optimal price point for Team: **$19** per seat per month.
- Range of acceptable prices: $14 to $26.
- Business buyers ignored per-seat framing entirely and anchored on annual contract value.

## Caveats

Trial users skew toward small teams, so the Business results are thin. We should repeat the
survey with interview participants from the [[Interview Synthesis March]] cohort.
Feeds into [[Tier Design]] and [[Discounting Policy]]. #willingness-to-pay
""")

note("product/pricing/Churn Analysis 2026.md", ["churn", "pricing", "retention"], """
# Churn Analysis 2026

We looked at 1,140 cancelled or downgraded accounts from January to September.

## Stated reasons

1. "Didn't get value fast enough" — 34%
2. Bill shock / unpredictable cost — 18%
3. Switched to a competitor — 15%
4. Price too high — 9%

## What it means

Price itself is rarely the problem; **time to value** is. Customers who connected a vault in the
first session churned at half the rate. That ties directly to the activation work in
[[Activation Metrics]] and the friction list in [[Onboarding Friction Themes]].

The bill shock finding motivated the [[Usage-Based Add-On]] redesign. #customer-churn
""")

note("product/pricing/Pricing Page Copy.md", ["pricing", "marketing"], """
# Pricing Page Copy

Draft headline: **"Pay for the people who use it."**

Sub-headline: Inactive seats are always free. Upgrade when your team grows, not before.

## FAQ drafts

**What counts as an active seat?** Anyone who opened Atlas in the billing month.

**Can I switch tiers mid-month?** Yes, we prorate to the day.

**Do you offer discounts?** Annual plans save 15%. See [[Discounting Policy]] for the internal rules.

Tone check against the [[Pricing Strategy#Principles]]: no fear-based upsell language.
""")

note("product/pricing/Packaging Experiments.md", ["pricing", "experiments"], """
# Packaging Experiments

A log of the packaging A/B tests on the pricing page.

## Experiment 1: decoy tier
Adding a Business tier with a visible price lifted Team conversion by 11%, but sales hated
publishing Business prices. Rolled back.

## Experiment 2: annual toggle default
Defaulting the toggle to annual raised annual mix from 31% to 44% with no drop in total
conversions. Kept.

## Experiment 3: seat slider
A seat slider showing the monthly total reduced support tickets about billing by a third.
Related to the predictability argument in [[Value Metric]] and the [[Tier Design]].
""")

note("product/pricing/Monetization Roadmap.md", ["pricing", "roadmap"], """
# Monetization Roadmap

Quarter by quarter:

- **Q1**: ship active-seat billing ([[Value Metric]]).
- **Q2**: usage add-on ([[Usage-Based Add-On]]) and the new [[Pricing Page Copy]].
- **Q3**: Business tier with SAML and audit log ([[Tier Design#Business]]).
- **Q4**: revisit discounts with fresh survey data.

Dependencies on the onboarding team: the self-serve funnel must improve first, otherwise more
pricing options just add confusion. See [[Activation Metrics]].
""")

# ---------------- Onboarding research ----------------
note("research/onboarding/Interview Synthesis March.md", ["onboarding", "user-research"], """
# Interview Synthesis March

Twelve interviews with new users in their first two weeks. Recruited from the trial cohort.

## Top themes

1. Users don't know what to do after the empty state. #onboarding-friction
2. The word "vault" confuses non-Obsidian users.
3. Seeing their *own* documents linked is the aha moment; sample data doesn't land.
4. People want a guided first search.

Full theme breakdown in [[Onboarding Friction Themes]]. Participant quotes are in
[[Interview Notes - Priya]] and [[Interview Notes - Marcus]].
""")

note("research/onboarding/Onboarding Friction Themes.md", ["onboarding", "friction"], """
# Onboarding Friction Themes

A running list of friction points, ranked by how often they appear across interviews,
support tickets and session recordings.

## 1. Empty state paralysis
New users land on an empty graph and leave. A "drop your files here" target helps.

## 2. Jargon
"Vault", "embedding", "cluster" all tested poorly. Plain words win.

## 3. Slow first index
If the first document takes more than a minute to appear, users assume it's broken.
This matches the churn finding that time to value drives cancellations, see
[[Churn Analysis 2026]].

## 4. No clear next step
After the graph appears, users don't know they can click and travel. See [[Guided Tour Prototype]].
""")

note("research/onboarding/Interview Notes - Priya.md", ["onboarding", "interview"], """
---
participant: Priya
role: Product manager
company_size: 40
---
# Interview Notes - Priya

> "I dropped in my spec folder and just stared at the dots. Which ones matter?"

Priya manages three product lines and keeps notes in Obsidian already. She loved that her
existing vault worked as-is, but expected the graph to highlight important notes.

Key moments:
- Found a link between two specs she had forgotten were related. Called it "spooky in a good way".
- Didn't discover the side panel until minute 12.
- Wants search results to show *why* something matched. #search #onboarding-friction

Follow up on her request for a weekly digest. Related: [[Onboarding Friction Themes#4. No clear next step]].
""")

note("research/onboarding/Interview Notes - Marcus.md", ["onboarding", "interview"], """
# Interview Notes - Marcus

Marcus is a PhD student with ~600 paper summaries in Markdown.

> "Clusters are the killer feature. I finally saw that my attention papers and my
> retrieval papers were the same pile."

- Wanted to rename cluster labels immediately.
- Hit the slow first index: 600 files took 25 minutes on his laptop. He almost quit.
- Would pay for it if his lab could share a graph.

He mentioned [[Attention Is All You Need]] and [[Retrieval-Augmented Generation]] as the two notes
that anchor his reading list. #clusters #onboarding-friction
""")

note("research/onboarding/Activation Metrics.md", ["onboarding", "metrics", "activation"], """
# Activation Metrics

**Definition**: a user is *activated* when they index 20+ documents and click from one document
to a linked document in the same session.

## Current numbers (trial cohort, October)

- Indexed 20+ docs in week 1: 29%
- Clicked a link in session 1: 41%
- Both: 22%

## Leading indicators

Users who run a search in the first 5 minutes are 2.3x more likely to activate.
Users who see a cluster summary card are 1.8x more likely.

Activation is the input to retention, which is the input to revenue ([[Monetization Roadmap]]).
See [[Churn Analysis 2026]] for the downstream effect.
""")

note("research/onboarding/Guided Tour Prototype.md", ["onboarding", "design"], """
# Guided Tour Prototype

A three-step tour that appears after the first 10 documents are indexed:

1. "These dots are your notes. Lines mean they talk about the same thing."
2. "Click any dot to see why it's connected."
3. "Try searching for something you wrote about recently."

## Test results

Five unmoderated sessions. Four of five completed the tour; all four clicked a link afterwards.
The one who skipped it was an Obsidian power user who found it patronising.
Make it skippable and never show it twice. Addresses [[Onboarding Friction Themes]].
""")

note("research/onboarding/Empty State Copy.md", ["onboarding", "copy"], """
# Empty State Copy

Options tested in a five-second test:

- A: "Your vault is empty." — 2/10 knew what to do.
- B: "Drop your .md files here to build your graph." — 8/10 knew what to do.
- C: "Connect a folder to get started." — 5/10.

Winner: **B**. Avoid the word vault in first-run copy ([[Interview Synthesis March]] theme 2).
""")

note("research/onboarding/Survey - First Week Experience.md", ["onboarding", "survey"], """
# Survey - First Week Experience

In-app survey shown on day 7, n=318.

| Question | Agree |
| --- | --- |
| "Atlas showed me a connection I didn't know about" | 57% |
| "I understood what the graph was showing" | 48% |
| "Setup was easy" | 71% |

Free-text answers repeat the same themes: the graph is beautiful but unclear, and indexing
large folders is slow. Several people asked for pricing that works for students, which feeds
the education discount in [[Discounting Policy]]. #onboarding-friction
""")

note("research/onboarding/Jobs To Be Done.md", ["onboarding", "jtbd"], """
# Jobs To Be Done

When I have **a pile of notes I never organised**, I want to **see what's in there without
tagging everything**, so I can **reuse what I already know**.

Secondary jobs:
- Prepare for a meeting by finding everything related to a client.
- Find the paper I half-remember. (See [[Interview Notes - Marcus|Marcus's interview]] — he described exactly this.)
- Spot themes across research interviews.

These jobs shape the activation definition in [[Activation Metrics]].
""")

note("research/onboarding/Session Recording Review.md", ["onboarding", "ux"], """
# Session Recording Review

Watched 30 first sessions in the recording tool.

Patterns:
- Median time to first upload: 48 seconds.
- 9 of 30 tried to drag a PDF; it was silently ignored. We should say "Markdown only" up front.
- 14 of 30 never opened the side panel.
- Hovering a node and reading the summary was the most common "delight" moment.

Recommendation: surface the side panel automatically on the first click.
Cross-reference: [[Onboarding Friction Themes]], [[Guided Tour Prototype]].
""")

# ---------------- ML papers ----------------
note("papers/ml/transformers/Attention Is All You Need.md", ["ml", "transformers", "paper"], """
---
title: Attention Is All You Need
authors: [Vaswani, Shazeer, Parmar, Uszkoreit, Jones, Gomez, Kaiser, Polosukhin]
year: 2017
---
# Attention Is All You Need

Introduces the **Transformer**: an encoder-decoder architecture built entirely from attention,
dropping recurrence and convolution.

## Key ideas

- Scaled dot-product attention: softmax(QK^T / sqrt(d_k)) V.
- Multi-head attention lets the model attend to different subspaces at once.
- Positional encodings (sinusoidal) inject order information.

## Why it matters

Parallelisable training made much larger models practical. Everything in [[BERT]] and
[[Scaling Laws for Neural Language Models]] builds on it. #attention #deep-learning

```python
def attention(q, k, v):
    return softmax(q @ k.T / sqrt(d)) @ v
```
""")

note("papers/ml/transformers/BERT.md", ["ml", "transformers", "nlp", "paper"], """
# BERT

*Pre-training of Deep Bidirectional Transformers for Language Understanding* (Devlin et al., 2018).

- Encoder-only [[Attention Is All You Need|Transformer]].
- Masked language modelling: hide 15% of tokens and predict them.
- Next sentence prediction (later shown to be mostly unnecessary).

Fine-tuning a single pre-trained model beat task-specific architectures on GLUE and SQuAD.
Sentence embeddings derived from BERT power early semantic search; compare with
[[Sentence-BERT]]. #nlp #embeddings
""")

note("papers/ml/transformers/Sentence-BERT.md", ["ml", "embeddings", "paper"], """
# Sentence-BERT

Reimers and Gurevych, 2019. Fine-tunes [[BERT]] with a siamese network so that cosine similarity
between sentence embeddings is meaningful.

## Why we care

This is the idea behind our own semantic links: embed every chunk, compare with cosine similarity,
keep the closest neighbours. Modern embedding models like nomic-embed-text follow the same
contrastive recipe at larger scale. See [[Contrastive Learning]] and [[Approximate Nearest Neighbor Search]].
#embeddings #semantic-search
""")

note("papers/ml/Retrieval-Augmented Generation.md", ["ml", "rag", "paper"], """
# Retrieval-Augmented Generation

Lewis et al., 2020. Combine a parametric generator with a non-parametric retriever over a document index.

## Mechanism

1. Embed the query with a dense encoder.
2. Retrieve top-k passages with [[Approximate Nearest Neighbor Search]].
3. Condition generation on the passages.

## Notes

Retrieval quality dominates answer quality. Hybrid retrieval (keyword + dense) usually beats
either alone; see [[Hybrid Search with Reciprocal Rank Fusion]]. #retrieval #rag
""")

note("papers/ml/Approximate Nearest Neighbor Search.md", ["ml", "vector-search"], """
# Approximate Nearest Neighbor Search

Exact KNN over millions of vectors is too slow, so we trade a little recall for a lot of speed.

## HNSW
Hierarchical Navigable Small World graphs: a layered proximity graph; search greedily descends
from sparse top layers to dense bottom layers. Great recall/latency trade-off; pgvector supports it.

## IVF
Partition vectors into lists around k-means centroids; search only the nearest lists.

## Parameters that matter
- `m` and `ef_construction` for HNSW build quality.
- `ef_search` at query time for recall.

Used by [[Retrieval-Augmented Generation]] and by our document linking. #vector-search
""")

note("papers/ml/Hybrid Search with Reciprocal Rank Fusion.md", ["ml", "search", "retrieval"], """
# Hybrid Search with Reciprocal Rank Fusion

Reciprocal Rank Fusion (Cormack et al., 2009) merges ranked lists without needing comparable scores:

score(d) = sum over lists of 1 / (k + rank(d)), with k = 60.

## Why it works

Keyword search (BM25 / tsvector) is precise on rare terms; dense retrieval handles paraphrase.
RRF rewards documents that rank well in both. Cheap, robust, no tuning beyond k.

Applied in [[Retrieval-Augmented Generation]] pipelines. #search #hybrid-search
""")

note("papers/ml/Contrastive Learning.md", ["ml", "representation-learning"], """
# Contrastive Learning

Learn representations by pulling positive pairs together and pushing negatives apart.

- **SimCLR**: augmentations of the same image are positives; large batches supply negatives.
- **InfoNCE loss**: a softmax over one positive and many negatives.
- In NLP, [[Sentence-BERT]] and later embedding models use contrastive objectives on
  question/answer or title/body pairs.

Temperature controls how hard the negatives are weighted. #embeddings #self-supervised
""")

note("papers/ml/HDBSCAN.md", ["ml", "clustering"], """
# HDBSCAN

Campello, Moulavi and Sander, 2013. Hierarchical density-based clustering.

## Why it's a good fit for document clustering

- No need to choose the number of clusters.
- Labels low-density points as noise instead of forcing them into a cluster.
- Works with arbitrary cluster shapes.

## Parameters

- `min_cluster_size`: the smallest group worth calling a theme.
- `min_samples`: how conservative the density estimate is.

On normalised embeddings, Euclidean distance is a monotone function of cosine distance, so
it works fine on [[Sentence-BERT]]-style vectors. #clustering #unsupervised
""")

note("papers/ml/Scaling Laws for Neural Language Models.md", ["ml", "scaling", "paper"], """
# Scaling Laws for Neural Language Models

Kaplan et al., 2020. Loss falls as a power law in parameters, data and compute, across many
orders of magnitude.

## Takeaways

- Bigger models are more sample-efficient.
- For a fixed compute budget, train a large model and stop before convergence.
- Later work (Chinchilla) revised the optimal data/parameter ratio upward.

Builds on the [[Attention Is All You Need]] architecture. #scaling #llm
""")

note("papers/ml/Topic Modeling Survey.md", ["ml", "topic-modeling", "nlp"], """
# Topic Modeling Survey

From LDA to embeddings.

## LDA
Documents are mixtures of topics; topics are distributions over words. Interpretable but
brittle on short texts.

## BERTopic
Embed documents, reduce with UMAP, cluster with [[HDBSCAN]], then extract topic words with
class-based TF-IDF. Much better on modern corpora.

## LLM topic extraction
Ask a language model for topics and entities directly, then merge near-duplicates by embedding
similarity ("ML" = "machine learning"). This is the approach Atlas uses. #topic-modeling
""")

# ---------------- Cooking ----------------
note("cooking/recipes/Sourdough Bread.md", ["cooking", "baking", "bread"], """
# Sourdough Bread

A reliable weekday loaf. Makes one boule.

## Ingredients
- 400 g bread flour, 100 g whole wheat
- 375 g water (75% hydration)
- 100 g active starter (see [[Sourdough Starter Care]])
- 10 g salt

## Method
1. Mix flour and water; rest 1 hour (autolyse).
2. Add starter and salt; squeeze to combine.
3. Four sets of stretch and folds, 30 minutes apart.
4. Bulk ferment until 50% risen, about 5 hours at 24 °C.
5. Shape, cold proof overnight, bake at 250 °C in a Dutch oven: 20 min lid on, 25 min lid off.

![crumb shot](images/crumb.jpg)

#baking #fermentation
""")

note("cooking/recipes/Sourdough Starter Care.md", ["cooking", "fermentation"], """
# Sourdough Starter Care

Feed 1:1:1 (starter : flour : water by weight) once a day at room temperature, or once a week
from the fridge.

## Signs of a healthy starter
- Doubles within 4 to 8 hours of feeding.
- Smells tangy, like yogurt; acetone smell means it's hungry.

## Troubleshooting
Hooch (grey liquid) on top: stir it in for more sour, pour it off for less.
Used in [[Sourdough Bread]] and [[Weekend Pancakes]]. #fermentation
""")

note("cooking/recipes/Weekend Pancakes.md", ["cooking", "breakfast"], """
# Weekend Pancakes

Uses sourdough discard from [[Sourdough Starter Care]].

- 200 g discard
- 1 egg, 1 tbsp sugar, pinch of salt
- 1/2 tsp baking soda, added right before cooking

Cook on a medium-hot buttered pan until bubbles pop on the surface, then flip. Serve with
maple syrup and berries. #breakfast #quick
""")

note("cooking/recipes/Ramen Broth.md", ["cooking", "japanese", "soup"], """
# Ramen Broth

A shoyu chintan broth, clear rather than creamy.

## Ingredients
- 1 kg chicken backs, 500 g wings
- Kombu (10 cm), dried shiitake, ginger, scallion whites

## Method
1. Blanch the bones, rinse, then simmer gently for 4 hours. Never boil, or it turns cloudy.
2. Steep kombu and shiitake off the heat for 30 minutes.
3. Strain; season each bowl with [[Tare]] rather than salting the pot.

Inspired by the bowls on the [[Tokyo Itinerary]] trip. #japanese #umami
""")

note("cooking/recipes/Tare.md", ["cooking", "japanese"], """
# Tare

Tare is the seasoning concentrate that defines a ramen bowl. Shoyu tare:

- 200 ml soy sauce
- 50 ml mirin, 50 ml sake
- 10 g kombu, a handful of bonito flakes

Warm gently to 80 °C, steep 20 minutes, strain. Use 30 ml per bowl of [[Ramen Broth]].
Keeps for a month in the fridge. #umami
""")

note("cooking/recipes/Pasteis de Nata.md", ["cooking", "baking", "portuguese"], """
# Pasteis de Nata

Portuguese custard tarts, the reason half of the [[Lisbon Notes]] trip happened.

## Custard
- 250 ml milk, 1 cinnamon stick, lemon peel
- 200 g sugar boiled with 100 ml water to 105 °C
- 6 egg yolks, 30 g flour

## Assembly
Roll puff pastry into a log, slice into 2 cm discs, press into muffin tins with wet thumbs.
Fill three-quarters, bake at the hottest your oven goes (290 °C) for 9 to 10 minutes until blistered.
#baking #dessert
""")

note("cooking/recipes/Weeknight Dal.md", ["cooking", "vegetarian", "indian"], """
# Weeknight Dal

Red lentil dal in 30 minutes.

1. Rinse 250 g red lentils; simmer with turmeric in 900 ml water for 20 minutes.
2. Tadka: heat ghee, add cumin seeds, mustard seeds, garlic, dried chilli; pour over the dal.
3. Finish with lemon juice and coriander.

Pairs with rice or flatbread. Freezes well. #vegetarian #meal-prep
""")

note("cooking/Meal Prep System.md", ["cooking", "planning"], """
# Meal Prep System

Sunday: two hours, three components.

- One grain (rice, farro).
- One protein or legume ([[Weeknight Dal]], roast chicken).
- One big tray of roasted vegetables.

Mix and match through the week. Bread comes from the [[Sourdough Bread]] bake on Saturday.
Shopping list lives in my phone, not here. #meal-prep
""")

note("cooking/Knife Skills.md", ["cooking", "technique"], """
# Knife Skills

Notes from the evening class.

- Claw grip: fingertips tucked, knuckles guide the blade.
- Rock chop for herbs, push cut for onions, pull cut for fish.
- Hone before every session; sharpen every few months.

Practice dish: brunoise of carrot, celery and onion for a mirepoix. #technique
""")

note("cooking/Fermentation Log.md", ["cooking", "fermentation"], """
# Fermentation Log

| Batch | Started | Notes |
| --- | --- | --- |
| Sauerkraut #3 | Sep 2 | 2% salt, ready after 3 weeks, very crunchy |
| Kimchi #1 | Sep 15 | Too much gochugaru; halve next time |
| Hot sauce | Oct 1 | Fresno + garlic, blend after 2 weeks |

Same principles as [[Sourdough Starter Care]]: temperature controls speed, salt controls which
microbes win. Want to try koji next, seen everywhere on the [[Tokyo Itinerary]]. #fermentation
""")

# ---------------- Travel ----------------
note("travel/japan/Tokyo Itinerary.md", ["travel", "japan"], """
# Tokyo Itinerary

Seven days, late March for the cherry blossoms.

## Day 1-2: Shinjuku and Shibuya
Omoide Yokocho for yakitori; Shinjuku Gyoen for hanami.

## Day 3: Asakusa and Ueno
Senso-ji early before the crowds. Ueno Park blossoms in the afternoon.

## Day 4: Day trip to Nikko
See [[Japan Rail Pass]] for whether the pass pays off.

## Day 5-7: Food
Ramen crawl (notes fed into [[Ramen Broth]]), Tsukiji outer market, depachika basements.

Hotel booking details in [[Kyoto Ryokan List]] for the second week.
""")

note("travel/japan/Japan Rail Pass.md", ["travel", "japan", "transport"], """
# Japan Rail Pass

After the 2023 price increase, the 7-day pass costs about ¥50,000. It pays off only with a
Tokyo-Kyoto-Hiroshima round trip or similar.

For a Tokyo-only stay with one day trip ([[Tokyo Itinerary#Day 4: Day trip to Nikko]]), a Suica
card and individual tickets are cheaper. #budget-travel
""")

note("travel/japan/Kyoto Temples.md", ["travel", "japan"], """
# Kyoto Temples

Short list for a three-day visit:

- **Fushimi Inari**: go at 7 am; the upper gates are empty.
- **Kinkaku-ji**: crowded but worth it once.
- **Ryoan-ji**: the rock garden is best on a quiet weekday.
- **Kiyomizu-dera**: sunset from the wooden stage.

Combine with the [[Tokyo Itinerary]] by shinkansen; see [[Japan Rail Pass]].
""")

note("travel/portugal/Lisbon Notes.md", ["travel", "portugal"], """
# Lisbon Notes

Five days in May.

- Tram 28 is a tourist crush; walk the Alfama instead.
- Best custard tarts: Manteigaria over Belém (controversial). Recipe attempt in [[Pasteis de Nata]].
- Day trip to Sintra; book Pena Palace tickets ahead.
- LX Factory on Sunday for the market.

Next stop: [[Porto Weekend]]. #europe
""")

note("travel/portugal/Porto Weekend.md", ["travel", "portugal"], """
# Porto Weekend

Train from Lisbon: 3 hours on the Alfa Pendular.

- Port cellars in Vila Nova de Gaia: Graham's tour is the best value.
- Francesinha at Café Santiago. Enormous.
- Walk the Dom Luís I bridge top deck at sunset.

Continued from [[Lisbon Notes]]. #europe
""")

note("travel/Packing List.md", ["travel", "planning"], """
# Packing List

Carry-on only, any season:

- 3 shirts, 1 sweater, 1 rain shell
- 2 trousers, 1 shorts
- Universal adapter, power bank, noise-cancelling headphones
- Packing cubes; a foldable tote for markets

Japan-specific: coin purse (cash still common) and slip-on shoes for temples ([[Kyoto Temples]]).
""")

note("travel/Travel Budget 2026.md", ["travel", "budget"], """
# Travel Budget 2026

| Trip | Flights | Stay | Food | Total |
| --- | --- | --- | --- | --- |
| Japan (12 days) | 1,150 | 1,400 | 700 | 3,250 |
| Portugal (8 days) | 420 | 760 | 380 | 1,560 |

Japan saving: skip the [[Japan Rail Pass]], use regional passes instead.
Portugal saving: stay in Porto guesthouses, not hotels. #budget-travel
""")

note("travel/Travel Photography Tips.md", ["travel", "photography"], """
# Travel Photography Tips

- Shoot blue hour, not golden hour, in cities: the lights come on and the sky stays blue.
- One prime lens (35 mm) forces better composition.
- Ask before photographing people; in Japan, never photograph geisha in Gion without permission.

Favourite shot so far: the Lisbon tram at dusk (`photos/lisbon-tram.png`, not a note).
""")

note("travel/Language Phrases.md", ["travel", "language"], """
# Language Phrases

## Japanese
- Sumimasen — excuse me / sorry
- Kore o kudasai — this one, please
- Okaikei onegaishimasu — the bill, please

## Portuguese
- Obrigado / obrigada — thank you (by speaker's gender)
- Uma bica, por favor — an espresso, please

Used constantly on the [[Tokyo Itinerary]] and in [[Lisbon Notes]].
""")

# Root-level index note
note("Welcome.md", None, """
# Welcome

This sample vault has five themes so the graph shows clear clusters:

- Product pricing: start at [[Pricing Strategy]]
- Onboarding research: start at [[Interview Synthesis March]]
- ML papers: start at [[Attention Is All You Need]]
- Cooking: start at [[Sourdough Bread]]
- Travel: start at [[Tokyo Itinerary]]

Some links point to notes that don't exist yet, like [[Competitor Teardown Q3]]; they show up as ghost nodes.
""", extra_fm="")

for path, (tags, extra, body) in N.items():
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    if body.startswith("---\n"):
        # body already carries its own frontmatter: merge tags in
        end = body.index("\n---\n", 4)
        fm, rest = body[4:end], body[end + 5:]
        if tags:
            fm += "\ntags: [" + ", ".join(tags) + "]"
        text = "---\n" + fm + "\n---\n" + rest
    elif tags:
        text = "---\ntags: [" + ", ".join(tags) + "]\ncreated: 2026-10-01\n---\n" + body
    else:
        text = body
    p.write_text(text, encoding="utf-8")

# Non-UTF-8 markdown (latin-1): must fail with NotUtf8.
(root / "cooking/recipes/Creme Brulee (latin1).md").write_bytes(
    "---\ntags: [cooking, dessert]\n---\n# Crème brûlée\n\nCrème, sucre, œufs... caramélisé au chalumeau.\n".encode("latin-1", errors="replace")
)
# Ignored files
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
(root / "travel/photos").mkdir(parents=True, exist_ok=True)
(root / "travel/photos/lisbon-tram.png").write_bytes(png)
(root / "inbox").mkdir(exist_ok=True)
(root / "inbox/todo.txt").write_text("- buy flour\n- book Porto train\n- send pricing survey\n")
print(len(N), "notes")
