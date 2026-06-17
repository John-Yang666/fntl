import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const commandComponents = [
  'src/components/SwitchModeComponent.vue',
  'src/components/SySwitchModeComponent.vue',
  'src/components/RestartCommandComponent.vue',
];

describe('command components authentication', () => {
  it('sends command APIs through requestWithAuth instead of raw axios calls', () => {
    for (const componentPath of commandComponents) {
      const source = readFileSync(resolve(process.cwd(), componentPath), 'utf8');

      expect(source).not.toMatch(/axios\.post\([^)]*send-command/s);
      expect(source).toContain('requestWithAuth');
    }
  });
});
