# Oracle API runtime

The single-user MVP keeps the FastAPI search service, immutable BM25 artifact, active Qdrant
collection, BGE-M3 and the reranker on the Oracle A1 VM. PostgreSQL metadata and raw files remain
in Supabase. Only the future HTTPS API gateway may be public; Qdrant and both internal services
listen on loopback.

## Private ports

- `127.0.0.1:8000`: FastAPI
- `127.0.0.1:8081`: embedding and reranker service
- `127.0.0.1:6333-6334`: Qdrant

Do not open these ports in the OCI security list. Until authentication, rate limiting and TLS are
configured, access FastAPI only through an SSH tunnel.

## Runtime files

- `/etc/bekenai/api.env`: root-owned mode `0600`; database and model-service secrets
- `/etc/bekenai/supabase-ca.crt`: Supabase dashboardından indirilen sunucu kök sertifikası
- `/opt/bekenai/current/retrieval_data`: immutable BM25 index and active manifest
- `/var/lib/bekenai-qdrant`: persistent Qdrant storage

`/etc/bekenai/api.env` içinde `SUPABASE_DB_SSL_ROOT_CERT=/etc/bekenai/supabase-ca.crt`
ayarlanmalıdır. Backend, ingestion ve retrieval bağlantıları `sslmode=verify-full` kullanır; sertifika
olmadan production bağlantısı başlatılmamalıdır.

## Checks

```bash
sudo systemctl status bekenai-api bekenai-qdrant bekenai-model-service
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:6333/healthz
```

The first fully remote `hybrid_rerank` smoke test returned 10 results from the deployed stack in
88.989 seconds on 2026-09-01. This is an accepted single-user MVP observation, not a p95 target.

For local testing:

```bash
ssh -N -L 8000:127.0.0.1:8000 -i /absolute/path/to/private.key ubuntu@SERVER_IP
```

## Private file ingestion (Stage 4)

The worker runs two lanes in one process: chat answers, verification and deletion in one,
`file_ingest` in the other, so a long document never delays an answer. Ingestion extracts
text (PDF via `pypdf`, DOCX and TXT via the standard library), chunks it, embeds each chunk
through the model service and writes:

- chunk text to `public.user_file_chunks` (no browser-role access; Turkish full-text index);
- vectors to the private Qdrant collection `beken_private_files_bge_m3_v1`, created on first
  use with payload indexes on `workspace_id` (tenant), `file_id`, `case_id` and
  `conversation_id`. It never shares a collection with `beken_global_*` indexes.

Deploy order: apply `20260927120000_add_private_file_ingestion.sql`, then restart the worker
and API. On start the worker queues files an older worker verified but never indexed. Before
restarting, confirm the worker venv can import the parser:

```bash
/opt/bekenai/venv/bin/python -c "import pypdf, qdrant_client"
```

Long documents heartbeat their job after every embedding batch, so stale-job recovery does
not re-run an ingest that is still making progress.

Chat answers search the chat's ready files alongside the global corpus: Qdrant (filtered to
the workspace and to the ready file ids the database returns) and Turkish full text over
`user_file_chunks`, fused with RRF and reranked by `bge-reranker-v2-m3`. File passages become
`SOURCE_FILE_*` evidence that only the answer's `file_answer` section may cite. While a file
in the chat's scope is still being verified or indexed, `POST /chat` returns
`409 files_processing`. Deleting a file redacts the passages earlier answers quoted from it.
Deletion removes vectors before the stored object; if it fails for good, a file that was
searchable comes back re-indexing rather than "ready" with half an index. Once a minute the
worker queues deletion for uploads whose intent expired more than 10 minutes ago (a closed tab);
they stay charged against the quota until that deletion has removed any object they left.

## Web search

Users can turn on web search in the composer, and an answer the corpus could not ground
offers it too (see ADR 0004). The usual answer is written as always; the web is searched
alongside and what it says is added after the answer as a labelled section. It needs one
secret in `/etc/bekenai/api.env`, read by both the API (to offer and accept web requests)
and the worker (to search):

```bash
TAVILY_API_KEY=tvly-...
```

Restart `bekenai-api` and `bekenai-worker` after adding it; `GET /chat/capabilities` then
returns `{"web_search": true}`. Without the key the option stays hidden. Optional settings:
`WEB_SEARCH_DEPTH` (`advanced`, 2 credits; `basic`, 1 credit), `WEB_SEARCH_MAX_RESULTS` (8)
and `WEB_SEARCH_TIMEOUT_SECONDS` (30). The free plan has 1,000 credits a month. A failed or
spent search never fails the answer: it arrives without the web section, which instead says
why (`web_search_status` in the answer records it).

Deploy order: apply `20260928154731_add_web_search_citations.sql` (adds
`chat_generations.search_mode` and the `web` citation scope), then restart the API and worker.

## Dependency advisories

Every pull request and push to `main` audits npm and both Python locks (CI). The
`Security audit` workflow repeats this every Monday, and also checks the pinned Qdrant image
against Qdrant's own advisories, so an advisory published while nothing changes still surfaces;
a failed run emails the repository owner. It can be run by hand from the Actions tab.

When it fails: npm and CI-only Python fixes are an ordinary pull request. A fix in
`deploy/oracle/*.lock` reaches production only through a new service venv (see
`oracle-model-service.md`), and a Qdrant fix through the stepwise upgrade described there.
GitHub's own Dependabot alerts cover npm and the direct Python dependencies, not the locked
transitive ones.
