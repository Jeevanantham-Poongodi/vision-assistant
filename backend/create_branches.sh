#!/usr/bin/env bash
# Run once by Coder 3, right after the first push to main.
set -e
for b in integration frontend-ui ai-core backend-api voice-ocr qa-docs; do
  git branch "$b" main
  git push -u origin "$b"
done
git checkout backend-api
echo "Done. You are now on backend-api."
