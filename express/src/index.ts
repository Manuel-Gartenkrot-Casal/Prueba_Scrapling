import express, { Request, Response } from 'express';
import axios, { AxiosError } from 'axios';
import http from 'http';
import path from 'path';

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const SCRAPERS_URL = process.env.SCRAPERS_URL || 'http://localhost:5000';

const VALID_SPIDERS = ['lanacion', 'aftermarket', 'ambito', 'cenital', 'perfil'] as const;
type Spider = typeof VALID_SPIDERS[number];

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

function extraerError(err: unknown): string {
  const axiosErr = err as AxiosError<{ error?: string; output?: string }>;
  return (
    axiosErr.response?.data?.error ||
    axiosErr.response?.data?.output ||
    'No se pudo conectar con el servicio de scrapers.'
  );
}

// ── Endpoints JSON (sin streaming, compatibilidad) ──────────────────────────

app.post('/api/run/:spider', async (req: Request, res: Response): Promise<void> => {
  const spider = req.params.spider as Spider;
  if (!(VALID_SPIDERS as readonly string[]).includes(spider)) {
    res.status(400).json({ success: false, error: `Spider '${spider}' no existe.` });
    return;
  }
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/run/${spider}`, {}, { timeout: 660_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.post('/api/run-all', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/run-all`, {}, { timeout: 1_800_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.post('/api/generar', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/generar`, {}, { timeout: 660_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.get('/api/health', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/health`, { timeout: 5_000 });
    res.json({ express: 'ok', scrapers: data });
  } catch {
    res.json({ express: 'ok', scrapers: 'unreachable' });
  }
});

// ── Endpoints streaming (proxy directo sin buffering) ───────────────────────

function crearProxyStreaming(rutaFlask: string) {
  return (req: Request, res: Response): void => {
    const parsed = new URL(SCRAPERS_URL);

    const opts: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || 5000,
      path: rutaFlask,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    };

    const proxyReq = http.request(opts, (proxyRes) => {
      res.status(proxyRes.statusCode || 200);
      res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('X-Accel-Buffering', 'no');
      proxyRes.pipe(res);
    });

    proxyReq.on('error', () => {
      res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
    });

    proxyReq.write(JSON.stringify({}));
    proxyReq.end();
  };
}

app.post('/api/stream/run/:spider', (req: Request, res: Response) => {
  const spider = req.params.spider as Spider;
  if (!(VALID_SPIDERS as readonly string[]).includes(spider)) {
    res.status(400).json({ success: false, error: `Spider '${spider}' no existe.` });
    return;
  }
  crearProxyStreaming(`/stream/run/${spider}`)(req, res);
});

app.post('/api/stream/run-all', crearProxyStreaming('/stream/run-all'));

app.post('/api/stream/generar', crearProxyStreaming('/stream/generar'));

// ── Endpoints para URLs custom ─────────────────────────────────────────────

app.post('/api/run-custom', async (req: Request, res: Response): Promise<void> => {
  const { urls, max } = req.body;
  if (!urls || !Array.isArray(urls) || urls.length === 0) {
    res.status(400).json({ success: false, error: 'Lista de URLs vacía.' });
    return;
  }
  try {
    const { data } = await axios.post(
      `${SCRAPERS_URL}/run-custom`,
      { urls, max: max || 5 },
      { timeout: 660_000 }
    );
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.post('/api/stream/run-custom', (req: Request, res: Response) => {
  const { urls, max } = req.body;
  if (!urls || !Array.isArray(urls) || urls.length === 0) {
    res.status(400).json({ success: false, error: 'Lista de URLs vacía.' });
    return;
  }
  const parsed = new URL(SCRAPERS_URL);
  const payload = JSON.stringify({ urls, max: max || 5 });
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/stream/run-custom',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => {
    res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
  });
  proxyReq.write(payload);
  proxyReq.end();
});

// ── Inicio ──────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`Express corriendo en http://localhost:${PORT}`);
  console.log(`Scrapers service: ${SCRAPERS_URL}`);
});
