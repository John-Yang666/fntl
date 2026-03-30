This directory is for vendored npm cache used by offline Docker builds.

Warm it once on a machine with network access, using the same Linux base image:

```sh
docker run --rm \
  -v "$PWD/frontend:/app" \
  -w /app \
  node:22 \
  sh -lc 'rm -rf npm-cache && npm ci --cache ./npm-cache'
```

Avoid warming this cache with macOS host npm directly. Linux-only optional packages
such as esbuild may be missing from the cache.

Then build offline with local base images:

```sh
docker build \
  --pull=false \
  -t my_vue:prod \
  -f frontend/Dockerfile.prod \
  --build-arg NODE_IMAGE=<local-node-image> \
  --build-arg NGINX_IMAGE=<local-nginx-image> \
  --build-arg NPM_INSTALL_MODE=offline \
  --build-arg VITE_BT_BACKEND_PORT=8000 \
  --build-arg VITE_SY_BACKEND_PORT=8001 \
  frontend
```
