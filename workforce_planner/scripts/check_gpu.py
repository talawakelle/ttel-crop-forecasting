from __future__ import annotations

import json
import sys

import torch


def main() -> int:
    available = torch.cuda.is_available()
    result = {
        "pytorch_version": torch.__version__,
        "cuda_available": available,
        "pytorch_cuda_runtime": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0) if available else None,
        "gpu_memory_gb": (
            round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)
            if available
            else None
        ),
    }
    print(json.dumps(result, indent=2))
    if not available:
        print(
            "\nGPU NOT READY: install the CUDA-enabled PyTorch build and update the NVIDIA driver.",
            file=sys.stderr,
        )
        return 1
    print("\nGPU READY: training will use the NVIDIA GPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
