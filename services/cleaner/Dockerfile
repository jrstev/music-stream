# Clean-library worker: Demucs + Whisper via music-profanity-filter.
#
# CPU build (default):   docker compose --profile cleaner build cleaner
# NVIDIA GPU build:      set CLEANER_TORCH_INDEX=https://download.pytorch.org/whl/cu124 in .env,
#                        rebuild, and uncomment the GPU block on the service in docker-compose.yml.
FROM python:3.11-slim

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
# Pinned upstream commit (2025-12-24); bump deliberately after checking its changes.
ARG MPF_REF=1632e72

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url "${TORCH_INDEX}" torch torchaudio \
 && pip install --no-cache-dir \
      "music-profanity-filter @ git+https://github.com/curtisgibby/music-profanity-filter@${MPF_REF}" \
      "mutagen>=1.47"

WORKDIR /app
COPY cleaner /app/cleaner

# Models (Demucs, Whisper) download on first use into /root/.cache - mount it to keep them.
ENV PYTHONUNBUFFERED=1
# music-profanity-filter writes its own CSV log to the working directory.
WORKDIR /data
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "cleaner"]
