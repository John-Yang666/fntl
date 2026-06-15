import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const candidates = [
  resolve(root, 'node_modules/.bin/vitest'),
  resolve(root, '../virtual-backend/node_modules/.bin/vitest'),
];

const vitestBin = candidates.find((candidate) => existsSync(candidate));
if (!vitestBin) {
  console.error('Vitest is not installed. Run `npm install` in frontend or virtual-backend first.');
  process.exit(1);
}

const result = spawnSync(vitestBin, ['run', '--config', resolve(root, 'vitest.config.ts')], {
  cwd: root,
  stdio: 'inherit',
});

process.exit(result.status ?? 1);
