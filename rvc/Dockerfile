# ---- Minimal rvc-python Dockerfile (Ubuntu 22.04) ----
# Minimal base image with only the essential runtime packages you requested.
FROM ubuntu:22.04


ARG DEBIAN_FRONTEND=noninteractive
ARG HOST_UID=1000
ARG USERNAME=rvc
ENV RVC_MODELS_DIR=/workspace/rvc_models


# Install system dependencies including build tools for fairseq/pyworld
RUN apt-get update && apt-get install -y --no-install-recommends \
python3.10 \
python3-pip \
python3.10-venv \
python3.10-dev \
build-essential \
ffmpeg \
libsndfile1 \
ca-certificates \
tzdata \
&& rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3.10 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip, setuptools, wheel
RUN pip install --no-cache-dir --upgrade "pip<24.1" setuptools wheel

# Install torch first (CUDA 11.8)
RUN pip install torch==2.1.1+cu118 torchaudio==2.1.1+cu118 --index-url https://download.pytorch.org/whl/cu118

# Install rvc-python
RUN pip install rvc-python

RUN pip install tensorboardX

# ======================================================================
# PATCH: Force FP32 mode for RTX 3050 and similar GPUs
# The RTX 3050 has issues with batch_norm in FP16 mode
# ======================================================================

# Patch 1: Add RTX 3050 to the list of GPUs that force FP32 in config.py
RUN sed -i 's/"1080" in self.gpu_name/"1080" in self.gpu_name or "3050" in self.gpu_name or "3060" in self.gpu_name/' \
    /opt/venv/lib/python3.10/site-packages/rvc_python/configs/config.py

# Patch 2: Safer approach - force is_half=False for all CUDA devices
# This replaces the default "is_half = True if device != cpu" with always False
RUN sed -i 's/self.is_half = True if device != "cpu" else False/self.is_half = False  # Forced FP32 for compatibility/' \
    /opt/venv/lib/python3.10/site-packages/rvc_python/configs/config.py

# Patch 3: Also set is_half=False in the XPU branch
RUN sed -i 's/self.is_half = True$/self.is_half = False  # Forced FP32/' \
    /opt/venv/lib/python3.10/site-packages/rvc_python/configs/config.py

# Print patched config for verification
RUN grep -n "is_half" /opt/venv/lib/python3.10/site-packages/rvc_python/configs/config.py || true



# Create a non-root user and workspace dirs
RUN useradd -m -u ${HOST_UID} -s /bin/bash ${USERNAME} || true
RUN mkdir -p ${RVC_MODELS_DIR} /workspace/data /workspace/logs && \
    chown -R ${HOST_UID}:${HOST_UID} /workspace && \
    chown -R ${HOST_UID}:${HOST_UID} /opt/venv
VOLUME ["/workspace/rvc_models"]


USER ${USERNAME}
WORKDIR /workspace
# Ensure venv bin is in path (it should be from earlier, but let's be safe and include user local bin too)
ENV PATH="/home/${USERNAME}/.local/bin:$VIRTUAL_ENV/bin:$PATH"

# Force FP32 mode to avoid batch_norm Half precision issues on some GPUs
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Copy wrapper script
COPY --chown=${HOST_UID}:${HOST_UID} rvc_fp32_wrapper.py /workspace/

# Default command - use cuda:0 device with FP32 wrapper
CMD ["python3", "/workspace/rvc_fp32_wrapper.py", "api", "-p", "5050", "-l", "-de", "cuda:0"]