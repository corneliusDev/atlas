"""Read side (PRD Output 4 "Read services"): no writes, ever.

- ``PgSearchService``: hybrid search (Postgres full text + pgvector, reciprocal rank fusion).
- ``PgGraphService``: global / local graph, link evidence; resolves [[wikilinks]] at read time
  and joins ``link_feedback`` into the graph.
- ``PgDocumentReader``, ``PgJobsStatusReader``, ``PgVaultReader``, ``PgHealthCheck``: the extra
  read models the HTTP layer needs (document view, progress tray, vault list, health). Their
  protocols live in ``atlas.read.protocols`` because ``atlas.ports`` (frozen contract) has none.

Import the concrete services from their modules (``atlas.read.search`` etc.); this package
init stays import-free so ``atlas.http`` can import ``atlas.read.protocols`` without cycles.
"""
