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

BGE-M3 runs from the Hub's own ONNX export. The reranker runs from our int8 ONNX export of the
pinned Hub revision (ADR 0005), which lives outside the Hub cache and is pinned by SHA-256.

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
sudo docker pull qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10
```

Qdrant reads storage written by the previous minor version only, so upgrade one minor at a time
and let each start once (1.15 → 1.16 → 1.17 → 1.18 → 1.19 on 2026-09-30; 1.17 dropped RocksDB).
Copy `/var/lib/bekenai-qdrant` while the service is stopped first; it is the rollback. After each
step compare every collection's `points/count` with the value before. The Python client
(`qdrant-client`) is pinned to the server's minor version in both `pyproject.toml` files.

## Service virtual environment

All three services run from `/opt/bekenai/venv`, a symlink to a venv built only from the
hash-locked files. Since 2026-09-30 `deploy/oracle/requirements.lock` also covers the backend's
dependencies; torch comes from `torch.lock`. Build a new venv next to the current one, test it,
then move the symlink; the previous venv stays as the rollback:

```bash
V=/opt/bekenai/venvs/$(date +%Y%m%d)
sudo install -m 0644 requirements.lock torch.lock /opt/bekenai/locks/
sudo python3.12 -m venv "$V"
sudo "$V/bin/python" -m pip install --no-deps --require-hashes --only-binary=:all: -r /opt/bekenai/locks/requirements.lock
sudo "$V/bin/python" -m pip install --no-deps --require-hashes --only-binary=:all: -r /opt/bekenai/locks/torch.lock
sudo "$V/bin/python" -m pip check
```

Before moving the symlink, start the model service from the new venv on port 8082 (a transient
`systemd-run` unit with the service's environment) and send the same queries, passages and
rerank pairs to both services. Embeddings must match (cosine 1.0) and reranker scores must be
equal, or the stored vectors and the validated reranker (ADR 0005) no longer hold. On
2026-09-30 onnxruntime 1.30 changed int8 reranker scores by up to 0.16 while tokenization was
identical, so onnxruntime stays at 1.29.0.

transformers 5 also reads `config.json` when it loads a tokenizer; the offline cache filled by
transformers 4 lacked it for BAAI/bge-m3, and the service failed to start. Fetch any such file
once, online, at the catalog's pinned revision:

```bash
sudo systemd-run --pipe --wait --uid=bekenai --gid=bekenai -E HF_HOME=/var/cache/bekenai-model-service/huggingface "$V/bin/python" -c 'from huggingface_hub import hf_hub_download; hf_hub_download("BAAI/bge-m3", "config.json", revision="5617a9f61b028005a4858fdac845db406aefb181", token=False)'
```

Then switch and restart; the model service restarts api and worker with it:

```bash
sudo ln -sfn "$V" /opt/bekenai/venv.next && sudo mv -Tf /opt/bekenai/venv.next /opt/bekenai/venv
sudo systemctl restart bekenai-model-service bekenai-api bekenai-worker
```

The first switch (2026-09-30) replaced a plain directory: it was moved to
`/opt/bekenai/venvs/legacy-20260901` before the symlink was created. Its console scripts point at
`/opt/bekenai/venv/bin/python`, so pointing the symlink back at it is still a working rollback.

## Oracle A1 MVP baseline

The labour-law retrieval profile sends the top 25 RRF candidates to the reranker and returns
the top 10. On the 2 OCPU / 12 GB Oracle A1 MVP host, a synthetic warm 25-passage request
measured 9.386 seconds on 2026-09-01. A full Supabase + BM25 + Qdrant + reranker request
using real, longer legal passages measured 90.014 seconds. These are operational observations,
not p95 claims; production scaling requires representative load tests and reranker optimization.

Since 2026-09-28 the reranker runs as int8 ONNX (ADR 0005). On the 4 OCPU host, 25 real
passages take 14.2 s (median, p95 18.1 s) instead of 46.6 s with PyTorch, measured on 40
evaluation queries with no external API calls.

## ONNX reranker artifact

The service loads `bge-reranker-v2-m3` from
`/var/lib/bekenai-model-service/artifacts/bge-reranker-v2-m3/int8/model.onnx` (the service's
`StateDirectory`; override with `MODEL_ARTIFACT_DIR`) and refuses to start if its SHA-256
differs from `artifact_sha256` in the catalog. The tokenizer still comes from the pinned Hub
revision in the offline cache.

To (re)create the file, install the conversion-only `onnx` package outside the service venv
and run the export as the service user (about 2 minutes, 8 GB of memory):

```bash
sudo mkdir -p /opt/bekenai-export && sudo /opt/bekenai/venv/bin/python -m pip install --no-deps --target /opt/bekenai-export onnx==1.23.0 ml_dtypes
sudo chown -R bekenai:bekenai /opt/bekenai-export
sudo systemd-run --pipe --wait --uid=bekenai --gid=bekenai -p WorkingDirectory=/opt/bekenai/current -E HF_HOME=/var/cache/bekenai-model-service/huggingface -E HF_HUB_OFFLINE=1 -E PYTHONPATH=/opt/bekenai/current/retrieval/src:/opt/bekenai-export /opt/bekenai/venv/bin/python -m beken_retrieval export-reranker-onnx --out /var/lib/bekenai-model-service/artifacts
```

The command prints the artifact path and SHA-256. With the pinned versions the export is
byte-for-byte reproducible; a different hash means a toolchain change, so re-validate the
ranking before pinning it. Rollback: switch `current` to a release whose catalog has
`"backend": "torch"` for the reranker and restart `bekenai-model-service`.
