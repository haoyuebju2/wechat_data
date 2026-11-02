const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {positionStore} = require('../src/offline-position.cjs');

test('floating position survives a new store instance without retaining other data', () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-position-test-'));
  const file = path.join(folder, 'position.json');
  const first = positionStore(file);
  assert.equal(first.read(), null);
  const value = {version: 1, x: 0, y: 0.65, dock: 'left'};
  first.write(value);
  assert.deepEqual(positionStore(file).read(), value);
  first.write({...value, x: 0.5, dock: null});
  assert.deepEqual(fs.readdirSync(folder), ['position.json']);
  assert.equal(fs.readFileSync(file, 'utf8').includes('conversation'), false);
  fs.unlinkSync(file); fs.rmdirSync(folder);
});

test('invalid geometry cannot overwrite a saved position, and corrupt files are ignored', () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-position-test-'));
  const file = path.join(folder, 'position.json'), store = positionStore(file);
  const value = {version: 1, x: 0.5, y: 1, dock: 'bottom'};
  store.write(value);
  for (const bad of [null, {...value, x: -1}, {...value, x: Infinity}, {...value, y: 2}, {...value, dock: 'invalid'}, {...value, file: 'private.json'}]) {
    assert.throws(() => store.write(bad)); assert.deepEqual(store.read(), value);
  }
  fs.writeFileSync(file, '{broken'); assert.equal(store.read(), null);
  fs.writeFileSync(file, ' '.repeat(1024)); assert.equal(store.read(), null);
  fs.unlinkSync(file); fs.rmdirSync(folder);
});
