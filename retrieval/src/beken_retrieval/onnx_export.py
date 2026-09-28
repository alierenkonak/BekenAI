"""Convert the pinned cross-encoder to a fused, int8-quantized ONNX model for the CPU.

Only this conversion needs PyTorch and the `onnx` package; the model service runs the
result with ONNX Runtime alone. The artifact is written to
<out>/<model key>/int8/model.onnx and its SHA-256 is what the catalog pins.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.model_loading import safe_model_loading
from beken_retrieval.reranking import file_sha256

OPSET = 17


def export_reranker(spec: ModelSpec, out_dir: Path) -> tuple[Path, str]:
    try:
        import torch
        from onnx import TensorProto
        from onnxruntime.quantization import QuantType, quantize_dynamic
        from onnxruntime.transformers import optimizer
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("The export needs torch, transformers, onnx and onnxruntime") from exc
    with safe_model_loading():
        tokenizer = AutoTokenizer.from_pretrained(
            spec.model_id, revision=spec.revision, trust_remote_code=False, token=False
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            spec.model_id,
            revision=spec.revision,
            trust_remote_code=False,
            token=False,
            use_safetensors=True,
            # ONNX Runtime's attention fusion recognises the eager attention graph.
            attn_implementation="eager",
        ).eval()
    config = model.config
    if config.num_labels != 1:
        raise ValueError("Expected a single-score cross-encoder")
    sample = tokenizer(
        [("kıdem tazminatı", "İşçinin kıdem tazminatı hakkı"), ("fesih", "Yazılı fesih")],
        padding=True,
        return_tensors="pt",
    )
    target = out_dir / spec.key / "int8" / "model.onnx"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        raw = Path(scratch) / "raw" / "model.onnx"
        fused = Path(scratch) / "fused" / "model.onnx"
        raw.parent.mkdir()
        fused.parent.mkdir()
        with torch.no_grad():
            torch.onnx.export(
                model,
                (sample["input_ids"], sample["attention_mask"]),
                str(raw),
                input_names=["input_ids", "attention_mask"],
                output_names=["logits"],
                dynamic_axes={
                    "input_ids": {0: "batch", 1: "sequence"},
                    "attention_mask": {0: "batch", 1: "sequence"},
                    "logits": {0: "batch"},
                },
                opset_version=OPSET,
                do_constant_folding=True,
                dynamo=False,
            )
        # Fuse attention, GELU and layer norms into ONNX Runtime's CPU kernels.
        optimized = optimizer.optimize_model(
            str(raw),
            model_type="bert",
            num_heads=config.num_attention_heads,
            hidden_size=config.hidden_size,
            opt_level=1,
            use_gpu=False,
        )
        optimized.save_model_to_file(str(fused), use_external_data_format=True)
        # Weights (and the embedding table) become int8 per channel; activations are
        # quantized on the fly, which suits variable-length passages.
        quantize_dynamic(
            str(fused),
            str(target),
            weight_type=QuantType.QInt8,
            per_channel=True,
            # Fused ops have no inferred output type; their outputs are float.
            extra_options={"MatMulConstBOnly": True, "DefaultTensorType": TensorProto.FLOAT},
        )
    return target, file_sha256(target)
