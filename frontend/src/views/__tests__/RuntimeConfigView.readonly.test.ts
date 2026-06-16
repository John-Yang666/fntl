import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const getTemplate = () => {
  const source = readFileSync(resolve(process.cwd(), 'src/views/RuntimeConfigView.vue'), 'utf8');
  const start = source.indexOf('<template>');
  const end = source.indexOf('<script setup lang="ts">');

  if (start === -1 || end === -1) {
    throw new Error('RuntimeConfigView.vue template block was not found.');
  }

  return source.slice(start, end);
};

describe('RuntimeConfigView readonly fields', () => {
  it('renders editable deploy host file fields before readonly fields', () => {
    const template = getTemplate();
    const fileFieldIndex = template.indexOf('getFileFieldsByGroup(system, group)');
    const readonlyIndex = template.indexOf('getReadonlyFieldsByGroup(system, group)');
    const source = readFileSync(resolve(process.cwd(), 'src/views/RuntimeConfigView.vue'), 'utf8');

    expect(fileFieldIndex).toBeGreaterThanOrEqual(0);
    expect(readonlyIndex).toBeGreaterThanOrEqual(0);
    expect(fileFieldIndex).toBeLessThan(readonlyIndex);
    expect(template).toContain('file-field-card');
    expect(template).toContain('type="textarea"');
    expect(template).toContain('field.help_text');
    expect(source).toContain('draftFileValues');
    expect(source).toContain('file_values: cloneValue(state.draftFileValues)');
    expect(source).toContain('normalizeDeployHostFileContent');
    expect(source).toContain('validateDeployHostFileContent');
  });

  it('adds a security group tab for readonly security settings', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/RuntimeConfigView.vue'), 'utf8');

    expect(source).toContain("type RuntimeConfigGroup = 'runtime' | 'auth' | 'cleanup' | 'security'");
    expect(source).toContain("const GROUP_ORDER: RuntimeConfigGroup[] = ['runtime', 'cleanup', 'auth', 'security']");
    expect(source).toContain("security: '安全参数'");
  });

  it('renders readonly runtime fields before editable runtime fields', () => {
    const template = getTemplate();
    const readonlyIndex = template.indexOf('getReadonlyFieldsByGroup(system, group)');
    const editableIndex = template.indexOf('getFieldsByGroup(system, group)');

    expect(readonlyIndex).toBeGreaterThanOrEqual(0);
    expect(editableIndex).toBeGreaterThanOrEqual(0);
    expect(readonlyIndex).toBeLessThan(editableIndex);
    expect(template).toContain('readonly-field-card');
    expect(template).toContain('readonly-field-description');
    expect(template).toContain('field.description');
  });
});
