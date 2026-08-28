# Frontend toolchain

The pm-evals browser product is a client-side React application. It does not
use server components, server actions, image optimization, or server-rendered
routes. The production artifact is therefore a static Vite build served by
nginx, with `/api/*` proxied to the real backend on the same origin.

## Direct dependency migration

| Dependency | Before | After | Migration implication |
| --- | --- | --- | --- |
| React | `19.2.4` | `19.2.4` | Component and runtime behavior are unchanged. |
| React DOM | `19.2.4` | `19.2.4` | The SPA now mounts through `createRoot`; the rendered component tree is unchanged. |
| Next.js | `15.5.20` | removed | No used product capability depended on Next. Root URL and same-origin API behavior are preserved by Vite/nginx. |
| Vite | transitive `8.1.5` | direct `8.1.5` | Owns development, production build, and local production-preview commands. |
| `@vitejs/plugin-react` | `5.2.0` | `5.2.0` | Remains the React transform used by Vitest and now the production build. |
| TypeScript | resolved `5.9.3` | pinned `5.9.3` | Strict checking is unchanged and deterministic. |
| `openapi-typescript` | `7.13.0` | removed | Removes the vulnerable Redocly, js-yaml, minimatch, and brace-expansion chain. |
| `@hey-api/openapi-ts` | absent | pinned `0.97.0` | The types-only plugin deterministically generates the committed schema and operation types. |
| Vitest | resolved `4.1.10` | pinned `4.1.10` | The existing 80 unit/component tests run unchanged. |

The nginx runtime is `nginx:1.28-alpine`; Node is present only in the build
stage. `BACKEND_URL` is evaluated when the container starts, rather than baked
into the JavaScript bundle. Local Vite preview applies the same `/api` proxy
contract.

## Generator selection and currentness

`openapi-typescript@7.13.0` fails the mandatory high-severity audit through
Redocly. The latest evaluated `@hey-api/openapi-ts@0.99.0` also has high
findings. Stable `@hey-api/openapi-ts@0.97.0` has zero critical/high findings
and supports a types-only output, so it is the smallest qualifying supported
generator under the owner decision.

The selected version has one disclosed moderate advisory,
`GHSA-hhx9-57xq-r5rw`. Its affected client-parameter template is not enabled by
the types-only configuration. Moving to the currently affected newer line
would reintroduce high-severity parser findings. The pin must be re-evaluated
when a newer release clears the complete audit graph.

CI runs generation from the committed OpenAPI document and refuses any diff in
`src/lib/api-types/`. Generated types are never maintained by hand.

## Parity and rollback

The migration must keep the existing component suite, real-backend browser
journeys, accessibility checks, 375px responsive checks, production build,
and digest-bound container preview green. The deterministic `BUILD_ID` is the
SHA-256 digest of the built file paths and contents.

Rollback is a normal revert of the migration merge; there is no data or API
migration. The vulnerable prior lockfile must not be promoted while its
critical/high audit gate remains red.
