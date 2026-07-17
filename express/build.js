const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

execSync('npx tsc', { cwd: __dirname, stdio: 'inherit' });

const src = path.join(__dirname, 'src', 'public');
const dst = path.join(__dirname, 'dist', 'public');
if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
fs.cpSync(src, dst, { recursive: true });
console.log('Build complete: dist/public/ updated');
