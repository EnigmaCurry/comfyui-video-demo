#!/usr/bin/env bash
## Download all models required by comfyui-video-demo workflows.
## Usage: COMFYUI_MODELS_DIR=/path/to/ComfyUI/models ./download_models.sh
##
## Set COMFYUI_MODELS_DIR to your ComfyUI models directory (the one containing
## checkpoints/, loras/, unet/, vae/, clip/, text_encoders/, upscale_models/).
##
## Set HF_TOKEN for gated models (Flux 2, LTX, etc.) — get one at:
##   https://huggingface.co/settings/tokens
##
## Only missing files are downloaded (existing files are skipped).

set -euo pipefail

: "${COMFYUI_MODELS_DIR:?Set COMFYUI_MODELS_DIR to your ComfyUI models directory}"

if [[ -z "${HF_TOKEN:-}" ]]; then
    echo "WARNING: HF_TOKEN is not set. Gated models will fail to download."
    echo "         Get a token at: https://huggingface.co/settings/tokens"
    echo ""
fi

download() {
    local dir="$1" file="$2" url="$3"
    local dest="${COMFYUI_MODELS_DIR}/${dir}/${file}"
    mkdir -p "${COMFYUI_MODELS_DIR}/${dir}"
    if [[ -f "$dest" ]]; then
        echo "SKIP  ${dir}/${file}  (already exists)"
        return
    fi
    echo "GET   ${dir}/${file}"
    if [[ -n "${HF_TOKEN:-}" ]]; then
        wget -q --show-progress --header="Authorization: Bearer ${HF_TOKEN}" -O "$dest" "$url"
    else
        wget -q --show-progress -O "$dest" "$url"
    fi
}

echo "=== Checkpoints ==="
download checkpoints/sd15 realisticVisionV51_v51VAE.safetensors \
    https://huggingface.co/frankjoshua/realisticVisionV51_v51VAE/resolve/main/realisticVisionV51_v51VAE.safetensors
download checkpoints/sd15 AnythingV5V3_v5PrtRE.safetensors \
    https://huggingface.co/ckpt/anything-v5.0/resolve/main/AnythingV5V3_v5PrtRE.safetensors
download checkpoints ltx-2.3-22b-distilled-fp8.safetensors \
    https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-distilled-fp8.safetensors

echo ""
echo "=== LoRAs ==="
download loras ltx2.3-transition.safetensors \
    https://huggingface.co/valiantcat/LTX-2.3-Transition-LORA/resolve/main/ltx2.3-transition.safetensors
download loras ltx-2.3-22b-distilled-lora-384.safetensors \
    https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors
download loras wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors \
    https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors
download loras wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors \
    https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors
# NOTE: Source unknown — update URL if you find it
# download loras illustration-1.0-qwen-image.safetensors \
#     https://huggingface.co/UNKNOWN/UNKNOWN/resolve/main/illustration-1.0-qwen-image.safetensors

echo ""
echo "=== Diffusion Models (UNet) ==="
download unet hidream_i1_fast_fp8.safetensors \
    https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files/diffusion_models/hidream_i1_fast_fp8.safetensors
download unet qwen_image_fp8_e4m3fn.safetensors \
    https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors
download unet z_image_bf16.safetensors \
    https://huggingface.co/Comfy-Org/z_image/resolve/main/split_files/diffusion_models/z_image_bf16.safetensors
download unet z_image_turbo_bf16.safetensors \
    https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors
download unet capybara_v0.1.safetensors \
    https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/diffusion_models/capybara_v0.1.safetensors
download unet wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors \
    https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
download unet wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors \
    https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors
download unet flux-2-klein-9b-kv-fp8.safetensors \
    https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-kv-fp8/resolve/main/flux-2-klein-9b-kv-fp8.safetensors
download unet acestep_v1.5_turbo.safetensors \
    https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/resolve/main/split_files/diffusion_models/acestep_v1.5_turbo.safetensors

echo ""
echo "=== VAE ==="
download vae qwen_image_vae.safetensors \
    https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors
download vae hunyuanvideo15_vae_fp16.safetensors \
    https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/vae/hunyuanvideo15_vae_fp16.safetensors
download vae wan_2.1_vae.safetensors \
    https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors
download vae flux2-vae.safetensors \
    https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors
download vae ae.safetensors \
    https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files/vae/ae.safetensors
download vae ace_1.5_vae.safetensors \
    https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/resolve/main/split_files/vae/ace_1.5_vae.safetensors

echo ""
echo "=== CLIP / Text Encoders ==="
download clip qwen_2.5_vl_7b_fp8_scaled.safetensors \
    https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors
download clip qwen_3_4b.safetensors \
    https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors
download clip qwen_3_8b_fp8mixed.safetensors \
    https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors
download clip umt5_xxl_fp8_e4m3fn_scaled.safetensors \
    https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
download clip sigclip_vision_patch14_384.safetensors \
    https://huggingface.co/Comfy-Org/sigclip_vision_384/resolve/main/sigclip_vision_patch14_384.safetensors

echo ""
echo "=== Text Encoders ==="
download text_encoders gemma_3_12B_it_fp4_mixed.safetensors \
    https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors

echo ""
echo "=== IP-Adapter ==="
download ipadapter ip-adapter-plus_sd15.safetensors \
    https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus_sd15.safetensors

echo ""
echo "=== CLIP Vision ==="
download clip_vision CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors \
    https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors

echo ""
echo "=== Upscale Models ==="
download upscale_models RealESRGAN_x4plus.safetensors \
    https://huggingface.co/Comfy-Org/Real-ESRGAN_repackaged/resolve/main/RealESRGAN_x4plus.safetensors

echo ""
echo "Done! Any files marked SKIP already existed."
