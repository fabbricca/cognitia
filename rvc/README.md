# How to build and run
## 1. (Optional) set your host UID so files written by container match your host user:
```
export HOST_UID=$(id -u)
```

## 2. Build & run with docker-compose (recommended):
```
docker compose up --build -d
```
If your ```docker compose``` binary doesn't support ```device_requests```, use the ```docker build``` + ```docker run``` variant that explicitly passes ```--gpus```:
```
# build
docker build --build-arg HOST_UID=$(id -u) -t rvc-python:cu118 .


# run (example mounting your local model and data folders)
docker run --rm -it --gpus all \
-p 5050:5050 \
-v ~/.ssh:/home/rvc/.ssh:ro \
-v $(pwd)/rvc_models:/workspace/rvc_models \
-v $(pwd)/data:/workspace/data \
rvc-python:cu118 \
python3 -m rvc_python api -p 5050 -l
```

# Notes & tips
- Driver/CUDA compatibility: The most common problem is host driver not supporting the CUDA version of the container (CUDA 11.8). If torch.cuda.is_available() is false or the container shows driver/version mismatch, upgrade the host NVIDIA driver. Test with nvidia-smi inside the container.
- Model storage: ./rvc_models is mounted inside /workspace/rvc_models. Put your downloaded/converted models there. Keep an eye on file ownership — we chown /workspace to the rvc user; building with HOST_UID=$(id -u) helps files be owned by your host user.
- ffmpeg & codecs: libsox-fmt-all and ffmpeg usually provide sufficient codec coverage for input/output. If you need additional proprietary codecs, install them on the host and bind-mount, or extend the Dockerfile to include them.
- Small images: the image will be large (CUDA + PyTorch). If you care about size, you can switch to a smaller nvidia/cuda:11.8-runtime-ubuntu22.04 tag or try using debian based runtime tags; but ensure ABI compatibility with the wheel you install.
- Debugging GPU from inside container:
```
docker exec -it rvc-python nvidia-smi
docker exec -it rvc-python python3 -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
```