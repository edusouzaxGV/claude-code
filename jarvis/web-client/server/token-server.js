// Minimal LiveKit token server for the ZEMARK web client.
//
// Mints a short-lived LiveKit access token granting a browser participant the
// right to join a room, publish its microphone, and subscribe to the agent's
// audio. The API secret stays on the server and is never sent to the browser.
//
// Verified against livekit-server-sdk 2.17.0 (July 2026).
//   - `AccessToken(apiKey, apiSecret, { identity, ttl })`
//   - `token.addGrant({ roomJoin, room, canPublish, canSubscribe })`
//   - `token.toJwt()` is ASYNC and returns a Promise<string>.
//
// Endpoint:
//   GET /token?room=<room>&identity=<identity>
//     -> { token, url }
//
// Run: `npm run token-server` (or `npm run dev` to run it alongside Vite).

import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { AccessToken } from 'livekit-server-sdk';

const {
  LIVEKIT_URL,
  LIVEKIT_API_KEY,
  LIVEKIT_API_SECRET,
  TOKEN_SERVER_PORT = '3001',
} = process.env;

if (!LIVEKIT_URL || !LIVEKIT_API_KEY || !LIVEKIT_API_SECRET) {
  console.error(
    'Missing env vars. Copy .env.example to .env and set LIVEKIT_URL, ' +
      'LIVEKIT_API_KEY and LIVEKIT_API_SECRET.',
  );
  process.exit(1);
}

const app = express();
// The Vite dev server runs on a different origin, so allow cross-origin GETs.
app.use(cors());

app.get('/token', async (req, res) => {
  try {
    // Sensible defaults so the client can call GET /token with no params.
    const room = String(req.query.room || 'zemark-room');
    const identity = String(req.query.identity || `web-user-${Date.now()}`);

    const at = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
      identity,
      // Token lifetime; the browser only needs it long enough to connect.
      ttl: '15m',
    });

    at.addGrant({
      roomJoin: true,
      room,
      canPublish: true, // publish the microphone
      canSubscribe: true, // hear the agent
    });

    // toJwt() is async in server-sdk v2.
    const token = await at.toJwt();
    res.json({ token, url: LIVEKIT_URL });
  } catch (err) {
    console.error('Failed to mint token:', err);
    res.status(500).json({ error: 'failed_to_mint_token' });
  }
});

app.get('/healthz', (_req, res) => res.json({ ok: true }));

const port = Number(TOKEN_SERVER_PORT);
app.listen(port, () => {
  console.log(`ZEMARK token server listening on http://localhost:${port}`);
});
