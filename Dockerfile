FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS ocr-build
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl g++ make autoconf automake libtool pkg-config libleptonica-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl -fsSL https://github.com/tesseract-ocr/tesseract/archive/refs/tags/5.5.1.tar.gz -o tesseract.tar.gz && echo 'a7a3f2a7420cb6a6a94d80c24163e183cf1d2f1bed2df3bbc397c81808a57237  tesseract.tar.gz' | sha256sum -c - && tar xzf tesseract.tar.gz && cd tesseract-5.5.1 && ./autogen.sh && ./configure --prefix=/opt/tesseract --disable-openmp && make -j2 && make install
FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends liblept5 libgl1 libglib2.0-0 tesseract-ocr-eng tesseract-ocr-osd && rm -rf /var/lib/apt/lists/*
COPY --from=ocr-build /opt/tesseract /opt/tesseract
ENV PATH="/opt/tesseract/bin:/opt/venv/bin:$PATH" LD_LIBRARY_PATH=/opt/tesseract/lib TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata PLEA_TESSERACT=/opt/tesseract/bin/tesseract HOME=/tmp XDG_CACHE_HOME=/tmp/.cache PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CRASH_WORKBOOK=portable CRASH_OCR=rapidocr CRASH_ISOLATE_PAGES=1 CRASH_SKIP_PREVIEWS=1 OMP_THREAD_LIMIT=1 TZ=America/New_York
WORKDIR /app
COPY deploy/requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv && pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY . /app
RUN python scripts/install_models.py && ln -s /opt/venv engines/crash_report/.venv && ln -s /opt/venv engines/plea_reports/.venv && mkdir -p engines/plea_reports/data /data/crash /data/plea && chown -R 10001:10001 /data engines/plea_reports/data
ENV CRASH_BATCHES=/data/crash PLEA_DATA=/data/plea JOB_RETENTION_HOURS=48 PLEA_UPLOAD_TIMES=/data/upload-times.json
USER 10001:10001
CMD ["python","server.py"]
FROM runtime AS test
USER root
COPY deploy/dev-requirements.lock /tmp/dev-requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/dev-requirements.lock
CMD ["python","-m","pytest"]
