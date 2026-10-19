#!/usr/bin/env bash
# Version rapide de Realistic Vision V5.1 (aperçu photoréaliste en quelques étapes), au format OpenVINO int8.
# À lancer une seule fois par machine, sous WSL.
#
# Sources officielles :
#   - SG161222/Realistic_Vision_V5.1_noVAE (CreativeML OpenRAIL-M) + stabilityai/sd-vae-ft-mse (MIT)
#   - latent-consistency/lcm-lora-sdv1-5 (OpenRAIL++) : extension qui permet de générer en 4 à 8 étapes
# L'extension est FUSIONNÉE dans les poids avant la conversion : OpenVINO GenAI 2026.4 échoue à l'appliquer à la
# volée (couches de convolution), mais un modèle fusionné est un modèle ordinaire.
# Environnement conda jetable « rv_convert » (optimum-intel est incompatible avec l'environnement du projet).
set -euo pipefail

OUT="${1:-$HOME/.cache/komian/models/realistic-vision-v5.1-lcm-int8-ov}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

source ~/miniforge3/etc/profile.d/conda.sh
if ! conda env list | grep -q "^rv_convert "; then
    conda create -y -q -n rv_convert python=3.11
fi
conda activate rv_convert
pip install -q --extra-index-url https://download.pytorch.org/whl/cpu "torch==2.14.1+cpu" \
    "optimum-intel[openvino,nncf]" "openvino==2026.4.1" diffusers transformers accelerate safetensors peft

python - "$WORK/rv51-lcm" <<'PY'
import json, sys
from pathlib import Path
import torch
from diffusers import AutoencoderKL, LCMScheduler, StableDiffusionPipeline
from huggingface_hub import snapshot_download

dst = Path(sys.argv[1])
src = snapshot_download("SG161222/Realistic_Vision_V5.1_noVAE",
                        allow_patterns=["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "unet/*"])
vae = AutoencoderKL.from_pretrained(snapshot_download("stabilityai/sd-vae-ft-mse",
                                                      allow_patterns=["config.json", "*.safetensors"]))
pipe = StableDiffusionPipeline.from_pretrained(src, vae=vae, safety_checker=None, feature_extractor=None,
                                               requires_safety_checker=False, torch_dtype=torch.float32)
pipe.load_lora_weights("latent-consistency/lcm-lora-sdv1-5")
pipe.fuse_lora()                 # extension intégrée aux poids du UNet
pipe.unload_lora_weights()
pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)  # planificateur LCM, pris en charge par OpenVINO
pipe.save_pretrained(dst, safe_serialization=True)
print("modèle fusionné :", dst, json.loads((dst / "scheduler/scheduler_config.json").read_text())["_class_name"])
PY

mkdir -p "$(dirname "$OUT")"
optimum-cli export openvino --model "$WORK/rv51-lcm" --task text-to-image --weight-format int8 "$OUT"
echo "Modèle converti : $OUT"
du -sh "$OUT"

conda deactivate
conda env remove -y -q -n rv_convert
