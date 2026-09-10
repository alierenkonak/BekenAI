# Oracle model service runbook

The model service runs the pinned `bge-m3` embedding model and
`bge-reranker-v2-m3` reranker on the Oracle ARM VM. It listens only on
`127.0.0.1:8081`; no inference port is opened in the OCI security list.

## Runtime contract

- `POST /v1/embeddings`: authenticated BGE-M3 query or passage embeddings.
- `POST /v1/rerank`: authenticated reranker scores for at most 50 passages.
- `GET /health/live`: process liveness.
- `GET /health/ready`: both pinned models are loaded.

The service refuses arbitrary model identifiers. Model revisions and safe artifacts are pinned in
`retrieval/config/models.json`.

The Oracle ARM runtime uses `deploy/oracle/requirements.lock`, generated for Python 3.12 on
Linux ARM64. Every transitive dependency and accepted artifact hash is fixed. The CPU-only PyTorch
wheel is bound to its official HTTPS URL and SHA-256 digest. Install only wheels from that lock,
then install the local retrieval package without dependency resolution or isolated build tooling:

```bash
python3.12 -m venv /opt/bekenai/venv
/opt/bekenai/venv/bin/python -m pip install --require-hashes --only-binary=:all: -r deploy/oracle/torch.lock -r deploy/oracle/requirements.lock
/opt/bekenai/venv/bin/python -m pip install --no-deps --no-build-isolation ./retrieval
/opt/bekenai/venv/bin/python -m pip check
```

`deploy/oracle/requirements.in` records the reviewed direct model versions. Regenerate the lock
for `aarch64-manylinux_2_31` with the CPU PyTorch backend; do not resolve it on the server during
deployment.

## Required server environment

`/etc/bekenai/model-service.env` must be owned by root with mode `0600` and contain:

```text
MODEL_SERVICE_TOKEN=<at-least-32-random-characters>
MODEL_CATALOG_PATH=/opt/bekenai/current/retrieval/config/models.json
```

Do not commit this file or print its value in deployment logs.

## Local development tunnel

Keep the inference port private and open an SSH tunnel when running the backend locally:

```bash
ssh -N -L 8081:127.0.0.1:8081 -i /absolute/path/to/private.key ubuntu@SERVER_IP
```

Configure the ignored local environment file with:

```text
MODEL_INFERENCE_URL=http://127.0.0.1:8081
MODEL_INFERENCE_TOKEN=<same-secret-as-the-server>
```

Runtime retrieval rejects non-loopback plain HTTP URLs. A future remotely deployed backend must use
an authenticated HTTPS or private-network endpoint.

## Operational checks

```bash
sudo systemctl status bekenai-model-service
sudo journalctl -u bekenai-model-service --since today
curl --fail http://127.0.0.1:8081/health/live
curl --fail http://127.0.0.1:8081/health/ready
```

Never include queries, passages, tokens, or provider URLs in application logs.

Before restarting Qdrant after a unit update, preload the exact multi-architecture manifest used
by the service:

```bash
sudo docker pull qdrant/qdrant:v1.15.4@sha256:6ac4807063bbecddca0250bfbcff52acf18c22263b904d12919349e6d0a408f1
```

## Oracle A1 MVP baseline

The labour-law retrieval profile sends the top 25 RRF candidates to the reranker and returns
the top 10. On the 2 OCPU / 12 GB Oracle A1 MVP host, a synthetic warm 25-passage request
measured 9.386 seconds on 2026-09-01. A full Supabase + BM25 + Qdrant + reranker request
using real, longer legal passages measured 90.014 seconds. These are operational observations,
not p95 claims; production scaling requires representative load tests and reranker optimization.
