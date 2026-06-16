import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const getScopedStyle = () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/HeaderComponent.vue'), 'utf8');
  const match = source.match(/<style scoped>([\s\S]*?)<\/style>/);

  if (!match) {
    throw new Error('HeaderComponent.vue scoped style block was not found.');
  }

  return match[1];
};

const getRule = (style: string, selector: string) => {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = style.match(new RegExp(`${escapedSelector}\\s*\\{([\\s\\S]*?)\\}`));

  if (!match) {
    throw new Error(`${selector} rule was not found.`);
  }

  return match[1];
};

describe('HeaderComponent responsive layout', () => {
  it('allows the header actions to wrap instead of clipping on narrow widths', () => {
    const style = getScopedStyle();
    const containerRule = getRule(style, '.tabs-container');
    const actionsRule = getRule(style, '.action-buttons');

    expect(containerRule).toContain('flex-wrap: wrap;');
    expect(containerRule).toContain('overflow: visible;');
    expect(actionsRule).toContain('position: static;');
    expect(actionsRule).toContain('flex-wrap: wrap;');
    expect(actionsRule).not.toContain('position: absolute;');
  });
});
