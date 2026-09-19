#!/bin/sh
set -eu
# Install the same OCR version used by the Mac; leave Ubuntu's binary intact.
cd /opt/lawdocs/build/tesseract-5.5.1
./autogen.sh
./configure --prefix=/opt/lawdocs/tesseract --disable-openmp
make -j2
make install
# Both engines use the existing, checksum-matched language files.
ln -sf /usr/share/tesseract-ocr/5/tessdata/eng.traineddata /opt/lawdocs/tesseract/share/tessdata/eng.traineddata
ln -sf /usr/share/tesseract-ocr/5/tessdata/osd.traineddata /opt/lawdocs/tesseract/share/tessdata/osd.traineddata
