"""Benchmark des modèles d'images candidats sur la machine cible.

Usage : python benchmarks/bench_models.py sd15 [--steps 20] [--size 512] [--device CPU|GPU]
Chaque essai, réussi ou non, est consigné dans benchmarks/results/.
"""
import argparse
import json
import platform
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import psutil

RESULTS = Path(__file__).resolve().parent / "results"

MODELS = {
    "sd15": {"repo": "stable-diffusion-v1-5/stable-diffusion-v1-5", "pipeline": "StableDiffusionPipeline",
             "licence": "CreativeML OpenRAIL-M"},
    "sdxl": {"repo": "stabilityai/stable-diffusion-xl-base-1.0", "pipeline": "StableDiffusionXLPipeline",
             "licence": "CreativeML OpenRAIL++-M"},
    "flux_schnell": {"repo": "black-forest-labs/FLUX.1-schnell", "pipeline": "FluxPipeline",
                     "licence": "Apache 2.0"},
    # Versions converties pour OpenVINO (Intel) : processeur ou puce graphique intégrée.
    "sd15_ov_fp16": {"repo": "OpenVINO/stable-diffusion-v1-5-fp16-ov", "engine": "openvino",
                     "licence": "CreativeML OpenRAIL-M"},
    "sd15_ov_int8": {"repo": "OpenVINO/stable-diffusion-v1-5-int8-ov", "engine": "openvino",
                     "licence": "CreativeML OpenRAIL-M"},
    "lcm_ov_int8": {"repo": "OpenVINO/LCM_Dreamshaper_v7-int8-ov", "engine": "openvino", "lcm": True,
                    "licence": "MIT", "default_steps": 6},
}
OV_CACHE = Path.home() / ".cache" / "komian" / "ov_cache"  # propre à chaque système (Windows / WSL)

# Brief de référence (annexe B) : scène d'ambiance sans personne ni texte.
PROMPT = ("interior of a home improvement store, aisles with shelves of tools and paint, "
          "wide angle, natural light, realistic photo, clean composition, empty space at the top")
NEGATIVE = "text, letters, logo, watermark, signage, people, blurry, distorted"


class PeakMemory:
    def __init__(self):
        self.peak = 0
        self._stop = threading.Event()
        self._proc = psutil.Process()

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, self._proc.memory_info().rss)
            time.sleep(0.25)

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--device", default="CPU", help="OpenVINO : CPU ou GPU (puce graphique Intel)")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    spec = MODELS[args.model]
    args.steps = args.steps or spec.get("default_steps", 20)
    engine = spec.get("engine", "diffusers")
    device = args.device.upper() if engine == "openvino" else "cpu"
    vm = psutil.virtual_memory()
    record = {
        "model": args.model, "repo": spec["repo"], "licence": spec["licence"], "date": stamp,
        "params": {"steps": args.steps, "size": args.size, "seed": args.seed, "prompt": PROMPT,
                   "negative": None if spec.get("lcm") else NEGATIVE, "engine": engine, "device": device},
        "machine": {"cpu": platform.processor(), "cores_logical": psutil.cpu_count(),
                    "ram_total_gb": round(vm.total / 2**30, 1), "ram_free_at_start_gb": round(vm.available / 2**30, 1)},
    }
    try:
        import diffusers
        import torch
        record["versions"] = {"torch": torch.__version__, "diffusers": diffusers.__version__}
        with PeakMemory() as mem:
            t0 = time.perf_counter()
            if engine == "openvino":
                import openvino
                import openvino_genai as ov_genai
                from huggingface_hub import snapshot_download
                record["versions"]["openvino"] = openvino.__version__
                record["versions"]["openvino_genai"] = ov_genai.__version__
                model_dir = snapshot_download(spec["repo"])
                record["download_and_files_s"] = round(time.perf_counter() - t0, 1)
                guidance = 8.0 if spec.get("lcm") else 7.5
                pipe = ov_genai.Text2ImagePipeline(model_dir)
                pipe.reshape(1, args.size, args.size, guidance)  # formes statiques : plus rapide
                pipe.compile(device, CACHE_DIR=str(OV_CACHE))
            else:
                pipe_cls = getattr(diffusers, spec["pipeline"])
                kwargs = {"dtype": torch.float32}
                if args.model in ("sd15", "sdxl"):
                    kwargs["variant"] = "fp16"  # poids fp16 téléchargés, calcul en float32 sur CPU
                if args.model == "sd15":
                    kwargs["safety_checker"] = None
                    kwargs["requires_safety_checker"] = False
                pipe = pipe_cls.from_pretrained(spec["repo"], **kwargs)
            if engine != "openvino":
                pipe.set_progress_bar_config(disable=True)
            record["load_s"] = round(time.perf_counter() - t0, 1)

            timings = []
            for _ in range(2):  # 1re génération = préparation incluse ; 2e = régime établi dans l'application
                t1 = time.perf_counter()
                if engine == "openvino":
                    from PIL import Image
                    call = {"width": args.size, "height": args.size, "num_inference_steps": args.steps,
                            "rng_seed": args.seed, "guidance_scale": guidance}
                    if not spec.get("lcm"):  # LCM : pas de prompt négatif
                        call["negative_prompt"] = NEGATIVE
                    image = Image.fromarray(pipe.generate(PROMPT, **call).data[0])
                else:
                    image = pipe(prompt=PROMPT, negative_prompt=NEGATIVE, num_inference_steps=args.steps,
                                 width=args.size, height=args.size,
                                 generator=torch.Generator("cpu").manual_seed(args.seed)).images[0]
                timings.append(round(time.perf_counter() - t1, 1))
            record["generate_first_s"], record["generate_s"] = timings
        record["peak_rss_gb"] = round(mem.peak / 2**30, 2)
        out = RESULTS / f"{args.model}_{device.lower()}_{stamp}.png"
        image.save(out)
        record["image"] = out.name
        record["status"] = "ok"
    except BaseException as exc:  # inclut MemoryError et interruption : l'échec doit rester visible
        record["status"] = "echec"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc(limit=5)
    path = RESULTS / f"{args.model}_{device.lower()}_{stamp}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items() if k != "traceback"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
