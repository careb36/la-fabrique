FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py audio.py engines.py models.py /app/

# The models live on a volume (/models): Kokoro's two files, fetched and
# checked by models.py, and faster-whisper's cache.
ENV SPEECH_KOKORO_DIR=/models/kokoro \
    HF_HOME=/models/hf \
    SPEECH_PORT=5200
RUN useradd --create-home --uid 1000 --user-group app && mkdir -p /models && chown -R app:app /models
USER app
VOLUME ["/models"]
EXPOSE 5200

CMD ["sh", "-c", "python models.py && python app.py"]
