#!/bin/bash
cp -r ../local-kit-source/*.py ./local_kit/
cp ../local-kit-source/VERSION ./local_kit/
git add local_kit/
git commit -m "sync: local_kit v$(cat ./local_kit/VERSION)"
