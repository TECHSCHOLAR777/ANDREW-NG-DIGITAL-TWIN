# Frontend

The frontend is a Next.js 16 and React 19 application containing the public
site, Auth.js account flow, conversation workspace, knowledge graph, and voice
interface.

Project-wide architecture, backend setup, privacy, and deployment instructions
live in the root [`README.md`](../README.md).

## Local development

Install dependencies:

```bash
cd frontend
npm ci
```

Create `frontend/.env.local`:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
AUTH_SECRET=replace_with_a_long_random_secret
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

`DATABASE_URL` is used by the signup and Auth.js server routes.
`NEXT_PUBLIC_API_BASE_URL` is used by the browser to call FastAPI.

Start the application:

```bash
npm run dev
```

Open `http://localhost:3000`.

## Routes

| Route | Purpose |
|---|---|
| `/` | Public landing page |
| `/understand` | Interactive architecture explanation |
| `/login` | Sign in |
| `/signup` | Create an account and adopt guest memory |
| `/app` | Conversation, graph, history, settings, and voice workspace |

## Quality checks

Run these before deploying:

```bash
npx tsc --noEmit
npm run lint
npm run build
```

The production build must receive the intended
`NEXT_PUBLIC_API_BASE_URL`. Public Next.js environment values are fixed at
build time, so changing the backend URL requires a redeploy.

## Deployment

The deployed frontend runs on Vercel with the project root set to `frontend`.
Configure:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
AUTH_SECRET=replace_with_a_production_secret
NEXT_PUBLIC_API_BASE_URL=https://your-backend.example
```

Add the final Vercel HTTPS origin to the backend's
`CORS_ALLOW_ORIGINS`.
