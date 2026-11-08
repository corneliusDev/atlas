-- Seed for tests/test_read_pg.py (Track E read services). Fake 768-d vectors: one-hot axes,
-- so cosine similarity is 1 for the same axis and 0 otherwise.
--
-- Default vault documents (ids ordered so DocumentPair.a < .b reads naturally):
--   P = pricing  ...0a01  product/pricing.md   cluster C1  origin vault   tags product,pricing
--   C = churn    ...0a02  research/churn.md    cluster C1  origin vault   tags research
--   K = kyoto    ...0a03  travel/kyoto.md      cluster C2  origin upload  tags travel
--   R = ramen    ...0a04  cooking/ramen.md     no cluster  origin vault   tags cooking
-- Second vault: X ...0b01 also talks about churn (must never leak into default-vault reads).

CREATE FUNCTION pg_temp.onehot(i int) RETURNS vector LANGUAGE sql AS $$
    SELECT (array_agg(CASE WHEN g = i THEN 1.0 ELSE 0.0 END ORDER BY g))::real[]::vector
    FROM generate_series(1, 768) AS g
$$;

INSERT INTO vaults (id, name, root_path) VALUES
    ('00000000-0000-0000-0000-000000000002', 'Second vault', '/nonexistent-second-vault');

INSERT INTO clusters (id, vault_id, label, centroid, color, size) VALUES
    ('00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-000000000001', 'Product', pg_temp.onehot(1), '#e6194b', 2),
    ('00000000-0000-0000-0000-00000000c002', '00000000-0000-0000-0000-000000000001', 'Travel', pg_temp.onehot(3), '#3cb44b', 1);

INSERT INTO documents (id, vault_id, path, origin, content_hash, title, frontmatter, summary, tags, doc_embedding, cluster_id, indexed_at) VALUES
    ('00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-000000000001', 'product/pricing.md', 'vault', 'h-pricing',
     'Pricing Strategy', '{"title": "Pricing Strategy", "owner": "ana"}', 'How we price tiers. Aimed at reducing churn.',
     '{product,pricing}', pg_temp.onehot(1), '00000000-0000-0000-0000-00000000c001', '2026-11-01T10:00:00Z'),
    ('00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-000000000001', 'research/churn.md', 'vault', 'h-churn',
     'Churn Analysis', '{}', 'Cohort churn analysis. Retention improves with onboarding.',
     '{research}', pg_temp.onehot(2), '00000000-0000-0000-0000-00000000c001', '2026-11-02T10:00:00Z'),
    ('00000000-0000-0000-0000-000000000a03', '00000000-0000-0000-0000-000000000001', 'travel/kyoto.md', 'upload', 'h-kyoto',
     'Kyoto Trip', '{}', NULL,
     '{travel}', pg_temp.onehot(3), '00000000-0000-0000-0000-00000000c002', '2026-11-03T10:00:00Z'),
    ('00000000-0000-0000-0000-000000000a04', '00000000-0000-0000-0000-000000000001', 'cooking/ramen.md', 'vault', 'h-ramen',
     'Ramen Recipe', '{}', 'Tonkotsu broth.',
     '{cooking}', pg_temp.onehot(4), NULL, '2026-11-04T10:00:00Z'),
    ('00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000002', 'other/churn.md', 'vault', 'h-x',
     'Other Churn', '{}', NULL,
     '{research}', pg_temp.onehot(2), NULL, '2026-11-05T10:00:00Z');

INSERT INTO chunks (id, document_id, ordinal, heading_path, heading_text, text, embedding) VALUES
    ('00000000-0000-0000-0000-0000000c0a01', '00000000-0000-0000-0000-000000000a01', 0, '{Pricing,Tiers}', 'Pricing > Tiers',
     'Three pricing tiers. The annual discount is designed to reduce churn among small teams (seats < 10 & monthly).', pg_temp.onehot(1)),
    ('00000000-0000-0000-0000-0000000c0a11', '00000000-0000-0000-0000-000000000a01', 1, '{Pricing,Competitors}', 'Pricing > Competitors',
     'Competitor pricing pages compared side by side.', pg_temp.onehot(5)),
    ('00000000-0000-0000-0000-0000000c0a02', '00000000-0000-0000-0000-000000000a02', 0, '{Cohorts}', 'Cohorts',
     'Monthly cohorts show churn falls after onboarding calls. Churn and retention are the key metrics.', pg_temp.onehot(2)),
    ('00000000-0000-0000-0000-0000000c0a03', '00000000-0000-0000-0000-000000000a03', 0, '{}', '',
     'Temples, a ryokan stay and an onsen evening.', pg_temp.onehot(3)),
    ('00000000-0000-0000-0000-0000000c0a04', '00000000-0000-0000-0000-000000000a04', 0, '{Broth}', 'Broth',
     'Simmer pork bones for twelve hours for a rich broth.', pg_temp.onehot(4)),
    ('00000000-0000-0000-0000-0000000c0b01', '00000000-0000-0000-0000-000000000b01', 0, '{}', '',
     'Churn churn churn in another vault.', pg_temp.onehot(2));

INSERT INTO topics (id, vault_id, canonical_name, name_key, aliases, kind, embedding, cluster_id) VALUES
    ('00000000-0000-0000-0000-0000000070a1', '00000000-0000-0000-0000-000000000001', 'Customer Retention', 'customer retention', '{retention}', 'concept', pg_temp.onehot(6), '00000000-0000-0000-0000-00000000c001'),
    ('00000000-0000-0000-0000-0000000070a2', '00000000-0000-0000-0000-000000000001', 'travel', 'travel', '{}', 'tag', NULL, NULL);

INSERT INTO document_topics (document_id, topic_id, salience) VALUES
    ('00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-0000000070a1', 0.6),
    ('00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-0000000070a1', 0.9),
    ('00000000-0000-0000-0000-000000000a03', '00000000-0000-0000-0000-0000000070a2', 1.0);

INSERT INTO wiki_links (source_doc_id, target_name, target_key, anchor, alias, ordinal) VALUES
    ('00000000-0000-0000-0000-000000000a01', 'Churn Analysis', 'churn analysis', 'Cohorts', NULL, 0),          -- title match -> C
    ('00000000-0000-0000-0000-000000000a01', 'Competitor Teardown Q3', 'competitor teardown q3', NULL, NULL, 1), -- ghost
    ('00000000-0000-0000-0000-000000000a02', 'product/pricing', 'product/pricing', NULL, 'pricing', 0),       -- path match -> P
    ('00000000-0000-0000-0000-000000000a03', 'Kyoto Ryokan List', 'kyoto ryokan list', NULL, NULL, 0),         -- ghost
    ('00000000-0000-0000-0000-000000000a04', 'kyoto', 'kyoto', NULL, NULL, 0),                                 -- stem match -> K
    ('00000000-0000-0000-0000-000000000a04', 'Ramen Recipe', 'ramen recipe', NULL, NULL, 1);                   -- self link: dropped

INSERT INTO semantic_links (vault_id, doc_a, doc_b, score, reason, evidence_chunk_ids) VALUES
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-000000000a02', 0.82,
     'Both tie pricing decisions to churn.', '{00000000-0000-0000-0000-0000000c0a01,00000000-0000-0000-0000-0000000c0a02}'),
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000a03', '00000000-0000-0000-0000-000000000a04', 0.40,
     NULL, '{00000000-0000-0000-0000-0000000c0a03,00000000-0000-0000-0000-0000000c0a04}'),
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-000000000a04', 0.60,
     'Spurious.', '{00000000-0000-0000-0000-0000000c0a02,00000000-0000-0000-0000-0000000c0a04}');

INSERT INTO link_feedback (vault_id, doc_a, doc_b, verdict) VALUES
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-000000000a04', 'hidden'),
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-000000000a03', 'added');

-- Jobs: pricing done; churn failed (not_utf8); kyoto has an old done row and a newer running
-- row (latest wins -> indexing); ramen pending; a pending recluster; one job in vault 2.
INSERT INTO jobs (id, vault_id, kind, path, dedup_key, payload, state, attempts, outcome, last_error, created_at, updated_at, finished_at) VALUES
    ('00000000-0000-0000-0000-00000000f001', '00000000-0000-0000-0000-000000000001', 'upsert', 'product/pricing.md', 'product/pricing.md',
     '{"kind":"upsert","vault":"00000000-0000-0000-0000-000000000001","path":"product/pricing.md","origin":"vault"}', 'done', 1,
     '{"kind":"indexed","document_id":"00000000-0000-0000-0000-000000000a01","path":"product/pricing.md","link_count":2,"topic_count":1,"cluster_id":null}',
     NULL, '2026-11-01T09:00:00Z', '2026-11-01T09:01:00Z', '2026-11-01T09:01:00Z'),
    ('00000000-0000-0000-0000-00000000f002', '00000000-0000-0000-0000-000000000001', 'upsert', 'research/churn.md', 'research/churn.md',
     '{"kind":"upsert","vault":"00000000-0000-0000-0000-000000000001","path":"research/churn.md","origin":"vault"}', 'failed', 1,
     NULL, '{"kind":"not_utf8","path":"research/churn.md"}', '2026-11-01T09:00:00Z', '2026-11-01T09:02:00Z', '2026-11-01T09:02:00Z'),
    ('00000000-0000-0000-0000-00000000f003', '00000000-0000-0000-0000-000000000001', 'upsert', 'travel/kyoto.md', 'travel/kyoto.md',
     '{"kind":"upsert","vault":"00000000-0000-0000-0000-000000000001","path":"travel/kyoto.md","origin":"upload"}', 'done', 1,
     '{"kind":"skipped","path":"travel/kyoto.md","reason":"unchanged"}', NULL, '2026-11-01T08:00:00Z', '2026-11-01T08:01:00Z', '2026-11-01T08:01:00Z'),
    ('00000000-0000-0000-0000-00000000f004', '00000000-0000-0000-0000-000000000001', 'upsert', 'travel/kyoto.md', 'travel/kyoto.md',
     '{"kind":"upsert","vault":"00000000-0000-0000-0000-000000000001","path":"travel/kyoto.md","origin":"upload"}', 'running', 2,
     NULL, '{"kind":"model_timeout","step":"embed"}', '2026-11-01T09:00:00Z', '2026-11-01T09:03:00Z', NULL),
    ('00000000-0000-0000-0000-00000000f005', '00000000-0000-0000-0000-000000000001', 'upsert', 'cooking/ramen.md', 'cooking/ramen.md',
     '{"kind":"upsert","vault":"00000000-0000-0000-0000-000000000001","path":"cooking/ramen.md","origin":"vault"}', 'pending', 0,
     NULL, NULL, '2026-11-01T09:00:00Z', '2026-11-01T09:00:30Z', NULL),
    ('00000000-0000-0000-0000-00000000f006', '00000000-0000-0000-0000-000000000001', 'recluster', NULL, '__recluster__',
     '{"kind":"recluster","vault":"00000000-0000-0000-0000-000000000001"}', 'pending', 0,
     NULL, NULL, '2026-11-01T09:00:00Z', '2026-11-01T09:00:00Z', NULL),
    ('00000000-0000-0000-0000-00000000f007', '00000000-0000-0000-0000-000000000002', 'upsert', 'other/churn.md', 'other/churn.md',
     '{"kind":"upsert","vault":"00000000-0000-0000-0000-000000000002","path":"other/churn.md","origin":"vault"}', 'failed', 3,
     NULL, '{"kind":"model_unavailable","detail":"down"}', '2026-11-01T09:00:00Z', '2026-11-01T09:00:00Z', '2026-11-01T09:00:00Z');
