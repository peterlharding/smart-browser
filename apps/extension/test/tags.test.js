import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  activeFragment, completeFragment, MAX_TAG_LENGTH, parseTags, suggest, tooLong,
} from '../src/lib/tags.js';

describe('parseTags', () => {
  it('splits on commas, spaces and newlines', () => {
    assert.deepEqual(parseTags('python, fastapi sqlalchemy\npostgres'),
      ['python', 'fastapi', 'sqlalchemy', 'postgres']);
  });

  it('lowercases, because the vocabulary already has Linux and linux as separate tags', () => {
    assert.deepEqual(parseTags('Python, FASTAPI'), ['python', 'fastapi']);
  });

  it('removes duplicates while keeping the order typed', () => {
    assert.deepEqual(parseTags('python, PYTHON, fastapi, python'), ['python', 'fastapi']);
  });

  it('drops empty fragments from trailing or doubled separators', () => {
    assert.deepEqual(parseTags('python, , fastapi,,'), ['python', 'fastapi']);
  });

  it('returns nothing for empty input', () => {
    for (const input of ['', '   ', ',,,', null, undefined]) {
      assert.deepEqual(parseTags(input), []);
    }
  });
});

describe('tooLong', () => {
  it('flags tags the varchar(32) column cannot hold', () => {
    const long = 'x'.repeat(MAX_TAG_LENGTH + 1);
    assert.deepEqual(tooLong(['python', long]), [long]);
  });

  it('accepts a tag of exactly the maximum length', () => {
    assert.deepEqual(tooLong(['x'.repeat(MAX_TAG_LENGTH)]), []);
  });
});

describe('activeFragment', () => {
  it('is the text after the last separator', () => {
    assert.equal(activeFragment('python, fast'), 'fast');
  });

  it('is empty just after a separator, so everything is offered', () => {
    assert.equal(activeFragment('python, '), '');
  });

  it('is the whole value when nothing has been separated yet', () => {
    assert.equal(activeFragment('pyth'), 'pyth');
  });
});

describe('completeFragment', () => {
  it('replaces the fragment being typed and leaves a separator', () => {
    assert.equal(completeFragment('python, fast', 'fastapi'), 'python, fastapi, ');
  });

  it('appends when the cursor sits after a separator', () => {
    assert.equal(completeFragment('python, ', 'fastapi'), 'python, fastapi, ');
  });

  it('handles the very first tag', () => {
    assert.equal(completeFragment('', 'python'), 'python, ');
  });
});

describe('suggest', () => {
  const vocabulary = [
    { name: 'python', count: 58 },
    { name: 'pytest', count: 4 },
    { name: 'typescript', count: 12 },
    { name: 'javascript', count: 45 },
  ];

  it('ranks prefix matches above substring matches', () => {
    const names = suggest(vocabulary, 'py').map((t) => t.name);
    assert.deepEqual(names.slice(0, 2), ['python', 'pytest']);
  });

  it('breaks ties by usage, not alphabetically', () => {
    const names = suggest(vocabulary, 'script').map((t) => t.name);
    assert.deepEqual(names, ['javascript', 'typescript']);
  });

  it('offers the most-used tags when nothing has been typed', () => {
    const names = suggest(vocabulary, '', { limit: 2 }).map((t) => t.name);
    assert.deepEqual(names, ['python', 'javascript']);
  });

  it('excludes tags already on the bookmark or already typed', () => {
    const names = suggest(vocabulary, 'py', { exclude: ['python'] }).map((t) => t.name);
    assert.deepEqual(names, ['pytest']);
  });

  it('respects the limit', () => {
    assert.equal(suggest(vocabulary, '', { limit: 3 }).length, 3);
  });

  it('survives a vocabulary containing the blank tag the audit found', () => {
    const names = suggest([...vocabulary, { name: '', count: 43 }], '').map((t) => t.name);
    assert.ok(!names.includes(''));
  });
});
