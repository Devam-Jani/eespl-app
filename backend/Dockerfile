# LibreDWG's dwg2dxf for the AutoCAD takeoff (DWG to DXF): built once from the GNU release, linked
# statically, and only the one program is copied into the app image. Newer GCC warns on its code,
# so warnings are not treated as errors.
FROM python:3.12-slim AS libredwg
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL https://ftp.gnu.org/gnu/libredwg/libredwg-0.13.3.tar.xz | tar -xJ
WORKDIR /src/libredwg-0.13.3
RUN ./configure --prefix=/opt/libredwg --disable-bindings --disable-python --disable-shared --enable-release --disable-docs > /tmp/configure.log 2>&1 \
    || (tail -40 /tmp/configure.log; exit 1)
RUN (make -j"$(nproc)" CFLAGS="-O2 -Wno-error" -C src && make -j"$(nproc)" CFLAGS="-O2 -Wno-error" -C programs dwg2dxf) > /tmp/make.log 2>&1 \
    || (tail -60 /tmp/make.log; exit 1)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Pango and fonts for WeasyPrint (tender PDF export); DejaVu has the rupee sign, Lohit the
# Gujarati and Hindi lines on the delivery note.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
       fonts-lohit-gujr fonts-lohit-deva \
    && rm -rf /var/lib/apt/lists/*

COPY --from=libredwg /src/libredwg-0.13.3/programs/dwg2dxf /opt/libredwg/bin/dwg2dxf

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 --retries 10 -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
