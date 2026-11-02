"use strict";
// Only floating-control geometry is stored here; callers cannot choose a path.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function validatePosition(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1 ||
      Object.keys(value).some(key => !['version', 'x', 'y', 'dock'].includes(key)) ||
      !Number.isFinite(value.x) || value.x < 0 || value.x > 1 ||
      !Number.isFinite(value.y) || value.y < 0 || value.y > 1 ||
      ![null, 'left', 'right', 'top', 'bottom'].includes(value.dock)) return null;
  return {version: 1, x: value.x, y: value.y, dock: value.dock};
}

function positionStore(file) {
  return {
    read() {
      try {
        if (fs.lstatSync(file).isSymbolicLink() || fs.statSync(file).size > 512) return null;
        return validatePosition(JSON.parse(fs.readFileSync(file, 'utf8')));
      } catch { return null; }
    },
    write(input) {
      const value = validatePosition(input);
      if (!value) throw new Error('Invalid floating-control position');
      if (fs.existsSync(file) && fs.lstatSync(file).isSymbolicLink()) throw new Error('Reparse paths disabled');
      fs.mkdirSync(path.dirname(file), {recursive: true});
      const temporary = file + '.' + crypto.randomUUID() + '.tmp';
      try {
        fs.writeFileSync(temporary, JSON.stringify(value), {flag: 'wx', mode: 0o600});
        fs.renameSync(temporary, file);
      } finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
      return value;
    }
  };
}
module.exports = {validatePosition, positionStore};
