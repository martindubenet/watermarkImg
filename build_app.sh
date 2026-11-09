#!/bin/zsh
# Builds AddWatermark.app next to this script. Needs the Xcode Command Line Tools.
# Run it again after any change to AddWatermarkApp/.
set -euo pipefail
cd "$(dirname "$0")"
APP="AddWatermark.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -O -o "$APP/Contents/MacOS/AddWatermark" AddWatermarkApp/main.swift
cp AddWatermarkApp/Info.plist "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"   # ad-hoc signature, enough for a locally built app
echo "Built: $PWD/$APP"
