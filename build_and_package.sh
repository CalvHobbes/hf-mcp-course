#!/bin/bash

# Build with PyInstaller
pyinstaller --onefile --add-data "../../templates:templates" server.py

# Copy .env to dist directory
cp .env dist/

echo "Build complete. .env copied to dist/" 