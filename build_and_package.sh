#!/bin/bash

# Build with PyInstaller
pyinstaller --onefile --add-data "../../templates:templates" server.py



echo "Build complete. server copied to dist/" 