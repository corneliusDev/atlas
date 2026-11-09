/**
 * Seed data for the mock API: 36 documents, 12 topics (6 concept/person/org + 6 tags) and
 * 2 ghost notes = 50 graph nodes, modelled on samples/vault. Everything is deterministic so
 * tests can refer to documents by title.
 */
import type { TopicKind } from "../api/types";

export const DEFAULT_VAULT = "00000000-0000-0000-0000-000000000001";

const pad = (n: number) => n.toString(16).padStart(12, "0");
export const docId = (i: number) => `d0c00000-0000-4000-8000-${pad(i + 1)}`;
export const topicId = (i: number) => `70c10000-0000-4000-8000-${pad(i + 1)}`;
export const clusterId = (i: number) => `c1000000-0000-4000-8000-${pad(i + 1)}`;
export const chunkId = (doc: number, ordinal: number) => `cc000000-0000-4000-${(8000 + ordinal).toString(16)}-${pad(doc + 1)}`;

export const PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"];

export interface SeedCluster {
  label: string;
}

export const SEED_CLUSTERS: SeedCluster[] = [
  { label: "Kitchen & fermentation" },
  { label: "Retrieval & ML papers" },
  { label: "Pricing & monetization" },
  { label: "Onboarding research" },
  { label: "Japan trip" },
];

export interface SeedTopic {
  name: string;
  kind: TopicKind;
}

export const TAGS = ["cooking", "fermentation", "ml", "pricing", "onboarding", "travel"] as const;

export const SEED_TOPICS: SeedTopic[] = [
  { name: "wild yeast", kind: "concept" },
  { name: "embeddings", kind: "concept" },
  { name: "pricing", kind: "concept" },
  { name: "onboarding friction", kind: "concept" },
  { name: "Marcus Lee", kind: "person" },
  { name: "Japan Rail", kind: "org" },
  ...TAGS.map((t) => ({ name: t, kind: "tag" as const })),
];

export interface SeedDoc {
  path: string;
  title: string;
  cluster: number | null;
  tags: string[];
  summary: string;
  wiki: string[]; // [[targets]], may be ghosts; "Target#Heading" or "Target|alias" allowed
  topics: [string, number][]; // [topic name, salience]
  body: string; // a paragraph of note text
}

const d = (
  path: string,
  cluster: number | null,
  tags: string[],
  summary: string,
  body: string,
  wiki: string[] = [],
  topics: [string, number][] = [],
): SeedDoc => ({
  path,
  title: path.split("/").pop()!.replace(/\.md$/, ""),
  cluster,
  tags,
  summary,
  body,
  wiki,
  topics,
});

export const SEED_DOCS: SeedDoc[] = [
  d("Welcome.md", null, [], "A short tour of this vault and how the folders are organised. Start here if you are new.",
    "This vault collects cooking notes, ML paper summaries, pricing work, onboarding research and travel plans. Begin with [[Pricing Strategy]] or [[Sourdough Bread]].",
    ["Pricing Strategy", "Sourdough Bread"]),

  // ---- cooking (cluster 0)
  d("cooking/Fermentation Log.md", 0, ["cooking", "fermentation"], "A running log of sauerkraut, kimchi and hot sauce batches. Salt ratio and temperature decide how fast each batch ferments.",
    "Same principles as sourdough: temperature controls speed and salt controls which microbes win. Want to try koji next, seen everywhere in Tokyo.",
    ["Sourdough Starter Care", "Tokyo Itinerary"], [["wild yeast", 0.6]]),
  d("cooking/Knife Skills.md", 0, ["cooking"], "Notes on grip, the claw technique and keeping a blade sharp. Practice on onions first.",
    "Pinch grip on the blade, claw with the guiding hand, and hone before every session. A dull knife is the dangerous one.", ["Meal Prep System"]),
  d("cooking/Meal Prep System.md", 0, ["cooking"], "A weekly system for cooking three base components on Sunday. It cuts weeknight cooking to fifteen minutes.",
    "Cook a grain, a braise and a sauce on Sunday. Weeknights combine them. Sharp knives make the prep go twice as fast.", ["Knife Skills", "Ramen Broth"]),
  d("cooking/recipes/Pasteis de Nata.md", 0, ["cooking"], "Portuguese custard tarts with laminated dough and a very hot oven. The blistered top needs 290 °C.",
    "Roll the dough into a log, slice, and press into tins with wet thumbs. Bake at the highest heat your oven allows."),
  d("cooking/recipes/Ramen Broth.md", 0, ["cooking"], "A tonkotsu-style broth simmered for twelve hours. Seasoned with tare at the bowl, not in the pot.",
    "Blanch the bones, then keep a rolling boil to emulsify the fat. Season each bowl with tare; ramen in Tokyo taught me the balance.",
    ["Tare", "Tokyo Itinerary"]),
  d("cooking/recipes/Sourdough Bread.md", 0, ["cooking", "fermentation"], "A country loaf with 75% hydration and an overnight cold proof. The starter must be at peak before mixing.",
    "Mix when the starter has doubled. Stretch and fold four times, shape, and retard overnight in the fridge for flavour.",
    ["Sourdough Starter Care"], [["wild yeast", 0.8]]),
  d("cooking/recipes/Sourdough Starter Care.md", 0, ["cooking", "fermentation"], "How to feed and store a wild yeast starter. Feed 1:5:5 when warm and keep it in the fridge between bakes.",
    "A starter is a colony of wild yeast and lactobacillus. Warmth speeds it up; a stiff starter keeps longer in the fridge.",
    [], [["wild yeast", 0.95]]),
  d("cooking/recipes/Tare.md", 0, ["cooking"], "Shoyu tare for ramen: soy, mirin and kombu. It is the salt and the identity of the bowl.",
    "Steep kombu overnight, add soy and mirin, and warm gently. Thirty millilitres per bowl.", ["Ramen Broth"]),

  // ---- ML papers (cluster 1)
  d("papers/ml/Approximate Nearest Neighbor Search.md", 1, ["ml"], "Survey of HNSW, IVF and product quantisation for vector search. HNSW gives the best recall per millisecond at our scale.",
    "HNSW builds a layered proximity graph; queries descend greedily. IVF partitions space with k-means. pgvector supports both.",
    ["Hybrid Search with Reciprocal Rank Fusion"], [["embeddings", 0.7]]),
  d("papers/ml/Contrastive Learning.md", 1, ["ml"], "How contrastive objectives pull similar pairs together in embedding space. In-batch negatives make it cheap.",
    "The InfoNCE loss treats other items in the batch as negatives. Larger batches give harder negatives and better embeddings.",
    ["Sentence-BERT"], [["embeddings", 0.85]]),
  d("papers/ml/HDBSCAN.md", 1, ["ml"], "Density-based clustering that finds clusters of varying density and labels outliers as noise. Good for document themes.",
    "HDBSCAN builds a hierarchy of density clusters and keeps the most stable ones. It needs no k, only a minimum cluster size."),
  d("papers/ml/Hybrid Search with Reciprocal Rank Fusion.md", 1, ["ml"], "Combining keyword and vector rankings with reciprocal rank fusion. RRF is robust and needs no score calibration.",
    "Score each document by the sum of 1/(k + rank) across retrievers. Keyword search catches exact names; vectors catch paraphrases.",
    ["Approximate Nearest Neighbor Search"], [["embeddings", 0.5]]),
  d("papers/ml/Retrieval-Augmented Generation.md", 1, ["ml"], "Grounding language model answers in retrieved passages. Retrieval quality matters more than model size.",
    "Retrieve the top passages, put them in the prompt with citations, and ask the model to answer only from them.",
    ["Hybrid Search with Reciprocal Rank Fusion"], [["embeddings", 0.4]]),
  d("papers/ml/transformers/Attention Is All You Need.md", 1, ["ml"], "The transformer paper: self-attention replaces recurrence. Multi-head attention lets the model attend to several positions at once.",
    "Scaled dot-product attention with positional encodings. Training parallelises across the sequence, unlike RNNs."),
  d("papers/ml/transformers/BERT.md", 1, ["ml"], "Bidirectional encoder pre-trained with masked language modelling. Fine-tunes well on classification tasks.",
    "Mask 15% of tokens and predict them from both sides. The [CLS] token is a poor sentence embedding without fine-tuning.",
    ["Attention Is All You Need"], [["embeddings", 0.45]]),
  d("papers/ml/transformers/Sentence-BERT.md", 1, ["ml"], "Siamese BERT networks that produce sentence embeddings comparable with cosine similarity. Makes semantic search practical.",
    "Fine-tune BERT in a siamese setup on NLI pairs; mean-pool token vectors. Cosine similarity then reflects meaning.",
    ["BERT", "Contrastive Learning"], [["embeddings", 0.9]]),

  // ---- pricing (cluster 2)
  d("product/pricing/Churn Analysis 2026.md", 2, ["pricing"], "Churn is concentrated in accounts that never finish setup. Price is cited by only 12% of churned customers.",
    "Customer churn spikes in month two. Accounts that skip onboarding churn at three times the rate; pricing complaints are a minority.",
    ["Pricing Strategy", "Onboarding Friction Themes"], [["pricing", 0.6], ["onboarding friction", 0.55]]),
  d("product/pricing/Discounting Policy.md", 2, ["pricing"], "Rules for sales discounts: at most 20% without approval, and never on monthly plans. Discounts expire at renewal.",
    "Annual prepay earns up to 20%. Anything larger goes to the pricing council. Discounts must not stack with promotions.",
    ["Pricing Strategy"], [["pricing", 0.7]]),
  d("product/pricing/Monetization Roadmap.md", 2, ["pricing"], "The sequence of pricing changes for the next four quarters. Usage-based add-ons come after the tier refresh.",
    "Q1 refresh tiers, Q2 introduce the usage add-on, Q3 revisit the value metric, Q4 international pricing.",
    ["Tier Design", "Value Metric"], [["pricing", 0.75]]),
  d("product/pricing/Pricing Strategy.md", 2, ["pricing"], "Atlas prices on value delivered, anchored by a free tier. Competitors price per seat, which punishes small teams.",
    "We anchor on a generous free tier and charge for scale. See the competitor teardown before changing list prices.",
    ["Competitor Teardown Q3", "Value Metric", "Tier Design"], [["pricing", 0.95]]),
  d("product/pricing/Tier Design.md", 2, ["pricing"], "Three tiers: Free, Pro and Team. Each tier unlocks one clear job rather than a pile of features.",
    "Free for individuals, Pro for power users, Team for shared vaults. Avoid more than three tiers on the pricing page.",
    ["Pricing Strategy"], [["pricing", 0.8]]),
  d("product/pricing/Value Metric.md", 2, ["pricing"], "Candidate value metrics compared: documents indexed, seats and queries. Documents indexed tracks value best.",
    "The value metric should grow with the value customers get. Seats punish small teams; documents indexed scales with use.",
    ["Pricing Strategy"], [["pricing", 0.85]]),
  d("product/pricing/Van Westendorp Survey.md", 2, ["pricing"], "Price sensitivity survey of 240 users. The acceptable range for Pro is $8 to $14 a month.",
    "Four questions: too cheap, cheap, expensive, too expensive. The optimal price point landed at $11.",
    ["Pricing Strategy"], [["pricing", 0.65]]),

  // ---- onboarding research (cluster 3)
  d("research/onboarding/Activation Metrics.md", 3, ["onboarding"], "Activation is defined as twenty documents uploaded in week one. Only 31% of new users reach it today.",
    "Users who upload twenty documents in week one retain at twice the rate. The drop-off happens before the first upload.",
    ["Onboarding Friction Themes"], [["onboarding friction", 0.6]]),
  d("research/onboarding/Empty State Copy.md", 3, ["onboarding"], "Copy options for the empty graph. \"Drop your .md files here\" tested best in hallway tests.",
    "Short, action-first copy wins. Avoid explaining embeddings on the empty state; show a drop zone instead.",
    ["Guided Tour Prototype"], [["onboarding friction", 0.4]]),
  d("research/onboarding/Guided Tour Prototype.md", 3, ["onboarding"], "A three-step guided tour prototype: upload, explore a cluster, open a link reason. Testers skipped step two.",
    "Step one asks for files, step two zooms into a theme, step three opens \"Why connected?\". Five of eight testers skipped the tour.",
    ["Empty State Copy", "Onboarding Friction Themes"], [["onboarding friction", 0.5]]),
  d("research/onboarding/Interview Notes - Marcus.md", 3, ["onboarding"], "Interview with Marcus Lee, a consultant with 400 call notes. He wants to find similar past engagements fast.",
    "Marcus never hand-links notes. Setup felt long because he did not know which folder to choose.",
    ["Interview Synthesis March"], [["Marcus Lee", 0.95], ["onboarding friction", 0.45]]),
  d("research/onboarding/Interview Notes - Priya.md", 3, ["onboarding"], "Interview with Priya, a PhD student with paper summaries. She wants to see which papers share methods.",
    "Priya already uses Obsidian. She was confused that the graph showed links she did not write.",
    ["Interview Synthesis March"], [["onboarding friction", 0.4]]),
  d("research/onboarding/Interview Synthesis March.md", 3, ["onboarding"], "Synthesis of twelve interviews. The biggest friction is choosing what to upload first, not the graph itself.",
    "Themes: unclear first step, distrust of automatic links until a reason is shown, delight once a surprising link appears.",
    ["Interview Notes - Marcus", "Interview Notes - Priya", "Onboarding Friction Themes"], [["onboarding friction", 0.8], ["Marcus Lee", 0.3]]),
  d("research/onboarding/Onboarding Friction Themes.md", 3, ["onboarding"], "The five recurring onboarding friction themes ranked by frequency. Unclear first step tops the list.",
    "1. Unclear first step. 2. Waiting for indexing. 3. Not trusting links. 4. Too many nodes at once. 5. No obvious next action.",
    ["Activation Metrics"], [["onboarding friction", 0.95]]),

  // ---- travel (cluster 4)
  d("travel/japan/Tokyo Itinerary.md", 4, ["travel"], "Five days in Tokyo: Tsukiji outer market, Shimokitazawa and a ramen crawl. Koji and fermentation shops in Kuramae.",
    "Day two is the ramen crawl. Day four is a day trip to Kyoto on the shinkansen with the rail pass.",
    ["Kyoto Day Trip", "JR Pass Notes"], [["Japan Rail", 0.5]]),
  d("travel/japan/Kyoto Day Trip.md", 4, ["travel"], "A day in Kyoto: Fushimi Inari at dawn, then Arashiyama. Book a ryokan if staying overnight.",
    "Leave Tokyo at 6:00 on the Nozomi. Fushimi Inari before the crowds, lunch in Nishiki market, Arashiyama in the afternoon.",
    ["Kyoto Ryokan List", "JR Pass Notes"], [["Japan Rail", 0.6]]),
  d("travel/japan/JR Pass Notes.md", 4, ["travel"], "Whether the Japan Rail pass pays off for this route. It does not unless we add Hiroshima.",
    "The 7-day pass costs more than two Tokyo-Kyoto round trips. Nozomi trains are excluded unless you pay the supplement.",
    [], [["Japan Rail", 0.95]]),
  d("travel/Language Phrases.md", 4, ["travel"], "Polite Japanese phrases for restaurants and trains. Sumimasen covers most situations.",
    "Sumimasen (excuse me), kore kudasai (this one please), okaikei onegaishimasu (the bill please)."),
  d("travel/Packing List.md", 4, ["travel"], "Packing list for a two-week autumn trip. Pack light; laundry is easy in Japan.",
    "Two pairs of shoes, a light rain jacket, a coin purse for cash, and a pocket wifi reservation."),
];

/** Hand-written cross-cluster links with specific reasons (title pairs). */
export const CROSS_LINKS: [string, string, number, string][] = [
  ["Churn Analysis 2026", "Onboarding Friction Themes", 0.81, "Both trace churn back to users who never finish setup."],
  ["Churn Analysis 2026", "Activation Metrics", 0.78, "Both use week-one activation to predict who stays."],
  ["Fermentation Log", "Sourdough Starter Care", 0.84, "Both explain how salt and temperature steer microbial fermentation."],
  ["Tokyo Itinerary", "Ramen Broth", 0.66, "Both centre on tonkotsu ramen and the Tokyo ramen crawl."],
  ["Hybrid Search with Reciprocal Rank Fusion", "Approximate Nearest Neighbor Search", 0.88, "Both cover vector retrieval; one fuses it with keyword ranking."],
  ["Interview Notes - Marcus", "Retrieval-Augmented Generation", 0.52, "Both are about finding the right past document for a question."],
  ["Value Metric", "Activation Metrics", 0.57, "Both pick documents uploaded as the number that tracks value."],
];
