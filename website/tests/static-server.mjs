import {createReadStream, existsSync, statSync} from 'node:fs';
import {createServer} from 'node:http';
import {extname, join, normalize} from 'node:path';

const site = normalize(join(import.meta.dirname, '../../site'));
const contentTypes = {'.css': 'text/css', '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.wasm': 'application/wasm'};

createServer((request, response) => {
  const relative = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname).replace(/^\/+/, '');
  let target = normalize(join(site, relative));
  if (!target.startsWith(site)) { response.writeHead(403).end(); return; }
  if (existsSync(target) && statSync(target).isDirectory()) target = join(target, 'index.html');
  if (!existsSync(target)) { response.writeHead(404).end(); return; }
  response.writeHead(200, {'content-type': contentTypes[extname(target)] ?? 'application/octet-stream'});
  createReadStream(target).pipe(response);
}).listen(4173, '127.0.0.1');
