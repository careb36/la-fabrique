import { describe, expect, it } from 'vitest';

import { CommandRegistry } from './registry';
import type { Action } from './types';

const actions: Action[] = [
  {
    id: 'approve',
    label: { es: 'aprobar', en: 'approve' },
    phrases: { es: ['aprob*', 'aprueb*', '^dale'], en: ['approv*', 'ship it'] },
    hint: { es: ['aprobá', 'apruebo'], en: ['approve', 'ship it'] },
    run: () => 'ok',
  },
  {
    id: 'launch',
    label: { es: 'lanzar una tarea', en: 'launch a task' },
    phrases: { es: ['lanz*'], en: ['launch*', 'go ahead with'] },
    items: () => [{ id: 'csv', label: { es: 'Exportar CSV', en: 'CSV export' }, words: { es: ['planilla'], en: ['spreadsheet'] } }],
    run: () => 'ok',
  },
];

describe('CommandRegistry', () => {
  const registry = new CommandRegistry(actions);

  it('lists what can be said, in each language', () => {
    expect(registry.help('es')).toBe('Podés decir: aprobar o lanzar una tarea.');
    expect(registry.help('en')).toBe('You can say: approve or launch a task.');
    expect(registry.labels()).toEqual({ es: ['aprobar', 'lanzar una tarea'], en: ['approve', 'launch a task'] });
  });

  it('finds an action by id', () => {
    expect(registry.action('launch')?.label.en).toBe('launch a task');
    expect(registry.action('nothing')).toBeUndefined();
  });

  it('hands a recognizer whole words to expect: the hints, else the phrases that are words', () => {
    const es = registry.vocabularyHint('es');
    expect(es).toContain('Aprobá. Apruebo. Exportar CSV. Planilla.');
    expect(es).not.toMatch(/[*^_]/);
    expect(es).not.toContain('Lanz.');
    expect(es).toContain('Ayuda');
    const en = registry.vocabularyHint('en');
    expect(en).toContain('Approve. Ship it. Go ahead with. CSV export. Spreadsheet.');
    expect(en).toContain('Help');
  });
});
