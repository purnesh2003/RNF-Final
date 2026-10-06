// Load test for the chat: many simulated members sign up, connect over websocket and chat.
// NOT yet run against a real server - treat as a starting point and watch the first small run.
//
//   Install k6: https://k6.io/docs/get-started/installation/
//   Run (start SMALL, e.g. PEAK=50, then 500, 2000 ...):
//     k6 run -e BASE_URL=https://staging.yourdomain.com -e PEAK=500 loadtest/chat.js
//
// IMPORTANT - use a STAGING copy, never your live site:
//   * set RATELIMIT_ENABLED=0 on it (otherwise the per-IP sign-up limit blocks the test), and
//   * it fills the database with fake "Load Test" members.
import http from 'k6/http';
import ws from 'k6/ws';
import { check } from 'k6';

const BASE = __ENV.BASE_URL;
const PEAK = Number(__ENV.PEAK || 200);

export const options = {
  scenarios: {
    chatters: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: PEAK },   // people arrive
        { duration: '5m', target: PEAK },   // everyone is online and chatting
        { duration: '1m', target: 0 },      // people leave
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    checks: ['rate>0.98'],
  },
};

const csrf = (html) => (html.match(/name="csrf_token" value="([^"]+)"/) || [])[1];

export default function () {
  const email = `load-${__VU}-${__ITER}-${Date.now()}@example.com`;
  const form = http.get(`${BASE}/register`);
  const reg = http.post(`${BASE}/register`, {
    csrf_token: csrf(form.body), name: 'Load Test', email,
    password: 'LoadTest-123', confirm: 'LoadTest-123',
  });
  check(reg, { 'signed up': (r) => r.status === 200 });

  const cookies = http.cookieJar().cookiesForURL(`${BASE}/`);
  const cookie = Object.keys(cookies).map((k) => `${k}=${cookies[k][0]}`).join('; ');
  const url = BASE.replace(/^http/, 'ws') + '/socket.io/?EIO=4&transport=websocket';

  const res = ws.connect(url, { headers: { Cookie: cookie, Origin: BASE } }, (socket) => {
    socket.on('message', (msg) => {
      if (msg.startsWith('0')) socket.send('40');   // Engine.IO hello -> join the chat namespace
      else if (msg === '2') socket.send('3');       // server ping -> answer pong
    });
    // each member posts roughly once every 30-60 seconds
    socket.setInterval(() => socket.send(`42["send_message",{"body":"hello from ${__VU}"}]`), 30000 + Math.random() * 30000);
    socket.setTimeout(() => socket.close(), 4 * 60 * 1000);   // stay ~4 minutes
  });
  check(res, { 'websocket connected': (r) => r && r.status === 101 });
}
