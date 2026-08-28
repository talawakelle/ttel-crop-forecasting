# VS Code and NVIDIA GPU Guide — v1.5

PowerShell is the simplest way to train. VS Code is optional for viewing or editing the code.

## Open in VS Code

From the project folder:

```powershell
code .
```

Select this interpreter:

```text
backend\.venv\Scripts\python.exe
```

## Verify CUDA

```powershell
& ".\backend\.venv\Scripts\python.exe" -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU')"
```

Expected:

```text
True
NVIDIA GeForce RTX 3060
```

## Train the recommended model

```powershell
.\TRAIN_HYBRID_RL_GPU.bat
```

The older `TRAIN_DYNAMIC_RL_GPU.bat` is retained only for comparison research. The recommended v1.5 model is selective hybrid RL.
