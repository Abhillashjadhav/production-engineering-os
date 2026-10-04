# Local frontend access

Run `npm run dev` for development, or `npm run build` followed by `npm run start`
for a built preview. Both listen at `http://127.0.0.1:3000` and proxy `/api` to
`BACKEND_URL`, which defaults to `http://127.0.0.1:8000`.

The loopback default also applies to `scripts/preview.sh` and the local
Playwright harness. It limits the frontend listener to the machine running it.

For a deliberately shared LAN or managed preview, use Vite's explicit override:

```bash
npm run dev -- --host 0.0.0.0
# Or, after building:
npm run start -- --host 0.0.0.0
```

These commands listen on every IPv4 interface. Network peers permitted by the
host's firewall and routing can reach the frontend and its `/api` proxy. Use
them only when that sharing is intended.

The Docker image serves built files through nginx, independently of these Vite
commands. Docker Compose continues to publish ports 3000 and 8000 only on
`127.0.0.1`.
