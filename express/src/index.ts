import express, { Request, Response } from 'express';
import axios, { AxiosError } from 'axios';
import path from 'path';

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const SCRAPERS_URL = process.env.SCRAPERS_URL || 'http://scrapers:5000';

const VALID_SPIDERS = ['lanacion', 'aftermarket', 'ambito', 'cenital', 'perfil'] as const;
type Spider = typeof VALID_SPIDERS[number];

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Saca el mensaje útil de un error de axios. Flask puede responder con `error`
// (fallos simples) o con `output` (el detalle de cada spider en /run-all), así
// que probamos ambos antes de caer al genérico de conexión.
function extraerError(err: unknown): string {
  const axiosErr = err as AxiosError<{ error?: string; output?: string }>;
  return (
    axiosErr.response?.data?.error ||
    axiosErr.response?.data?.output ||
    'No se pudo conectar con el servicio de scrapers.'
  );
}

// Dispara un spider llamando al servicio Python
app.post('/api/run/:spider', async (req: Request, res: Response): Promise<void> => {
  const spider = req.params.spider as Spider;

  if (!(VALID_SPIDERS as readonly string[]).includes(spider)) {
    res.status(400).json({ success: false, error: `Spider '${spider}' no existe.` });
    return;
  }

  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/run/${spider}`, {}, {
      timeout: 660_000, // 11 min (el spider tiene 10 min internos)
    });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// Corre TODOS los spiders de una sola vez
app.post('/api/run-all', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/run-all`, {}, {
      timeout: 1_800_000, // 30 min (5 spiders en serie x 5 min internos + margen)
    });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// Genera el artículo reescrito por la IA
app.post('/api/generar', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/generar`, {}, {
      timeout: 660_000, // 11 min
    });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// Health check de ambos servicios
app.get('/api/health', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/health`, { timeout: 5_000 });
    res.json({ express: 'ok', scrapers: data });
  } catch {
    res.json({ express: 'ok', scrapers: 'unreachable' });
  }
});

app.listen(PORT, () => {
  console.log(`Express corriendo en http://localhost:${PORT}`);
  console.log(`Scrapers service: ${SCRAPERS_URL}`);
});

// Para agregar un spider nuevo al dashboard:
//   1. Agregar el nombre a VALID_SPIDERS
//   2. Agregar el botón correspondiente en src/public/index.html
