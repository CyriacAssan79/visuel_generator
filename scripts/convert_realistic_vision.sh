#!/usr/bin/env bash
# Conversion de Realistic Vision V5.1 au format OpenVINO int8 (à lancer une seule fois par machine, sous WSL).
#
# Sources officielles, au format safetensors :
#   - SG161222/Realistic_Vision_V5.1_noVAE (CreativeML OpenRAIL-M) : encodeur de texte, UNet, tokenizer
#   - stabilityai/sd-vae-ft-mse (MIT) : VAE recommandé par l'auteur (sans lui, couleurs délavées et artefacts)
#
# optimum-intel est incompatible avec l'environnement du projet (conflit huggingface-hub / diffusers) :
# la conversion se fait dans un environnement conda jetable, « rv_convert », supprimé à la fin.
# Mémoire : la conversion charge le modèle complet en float32 (prévoir ~8 Go, swap WSL compris).
set -euo pipefail

OUT="${1:-$HOME/.cache/komian/models/realistic-vision-v5.1-int8-ov}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

source ~/miniforge3/etc/profile.d/conda.sh
if ! conda env list | grep -q "^rv_convert "; then
    conda create -y -q -n rv_convert python=3.11
fi
conda activate rv_convert
pip install -q --extra-index-url https://download.pytorch.org/whl/cpu "torch==2.14.1+cpu" \
    "optimum-intel[openvino,nncf]" "openvino==2026.4.1" diffusers transformers accelerate safetensors

# Modèle au format diffusers, avec le VAE sd-vae-ft-mse à la place du VAE d'origine
python - "$WORK/rv51" <<'PY'
import shutil, sys
from pathlib import Path
from huggingface_hub import snapshot_download

PARTS = ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "unet/*"]
dst = Path(sys.argv[1])
src = Path(snapshot_download("SG161222/Realistic_Vision_V5.1_noVAE", allow_patterns=PARTS))
vae = Path(snapshot_download("stabilityai/sd-vae-ft-mse",
                             allow_patterns=["config.json", "diffusion_pytorch_model.safetensors"]))

def link(file: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(file.resolve())  # lien vers le cache : pas de copie des 4 Go

# Uniquement les composants retenus (le cache peut contenir d'autres fichiers du dépôt, dont son VAE)
for part in PARTS:
    for file in src.glob(part):
        link(file, dst / file.relative_to(src))
for name in ("config.json", "diffusion_pytorch_model.safetensors"):
    link(vae / name, dst / "vae" / name)
PY

# Pas de vérificateur de contenu (« safety checker ») : le projet ne l'utilise pas, comme pour SD 1.5
python - "$WORK/rv51/model_index.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
index = json.loads(path.read_text())
for key in ("safety_checker", "feature_extractor"):
    index[key] = [None, None]
index["requires_safety_checker"] = False
path.unlink()  # c'est un lien vers le cache Hugging Face : écrire une copie locale, sans toucher au cache
path.write_text(json.dumps(index, indent=2))
PY

mkdir -p "$(dirname "$OUT")"
optimum-cli export openvino --model "$WORK/rv51" --task text-to-image --weight-format int8 "$OUT"

# Le dépôt déclare le planificateur DEIS, refusé par OpenVINO GenAI : Euler Ancestral, recommandé par l'auteur
python - "$OUT/scheduler/scheduler_config.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text())
keep = ("beta_start", "beta_end", "beta_schedule", "num_train_timesteps", "prediction_type", "steps_offset",
        "trained_betas")
config = {"_class_name": "EulerAncestralDiscreteScheduler", "timestep_spacing": "linspace",
          **{k: config[k] for k in keep if k in config}}
path.write_text(json.dumps(config, indent=2))
PY
echo "Modèle converti : $OUT"
du -sh "$OUT"

conda deactivate
conda env remove -y -q -n rv_convert
