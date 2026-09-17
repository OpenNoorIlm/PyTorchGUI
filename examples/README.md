# Example pipelines

Open any of these in the editor with **File → Open…**, then:

* **Ctrl+G** (Generate) — writes `generated.py` from the current graph
* **F5** (Run) — executes `generated.py` and streams live output back to
  each node on the canvas

| File | What it does |
|---|---|
| `01_hello.json` | Minimal Start → Import torch → Tensor → End |
| `02_gpu_inspect.json` | Enumerate GPUs and pick a device |
| `03_cnn.json` | Chain nn.Conv2d / ReLU / MaxPool2d / Flatten / Linear inside nn.Sequential |
| `04_data_pipeline.json` | Image Input → Tensor → Sampler → Viewer with real data edges |
| `05_dynamic_merger.json` | 8 GPU outputs merged into one value by a dynamic Merger node |
| `06_download.json` | Pull a model from HuggingFace or GitHub |

## Regenerating

If you update the node templates and an example no longer opens cleanly,
just run:

    python createExample.py

That rewrites every file in `examples/` from the latest schema.
