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
