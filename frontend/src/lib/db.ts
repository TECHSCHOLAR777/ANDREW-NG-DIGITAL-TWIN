import { Pool } from "pg"

/**
 * Postgres pool for the Next.js server layer (authentication and signup).
 *
 * The FastAPI backend still owns the domain data; this connects to the SAME
 * Neon database only for the credential-account rows that Auth.js needs. A
 * single pool is cached on globalThis so Next's dev HMR does not open a new
 * pool on every reload and exhaust Neon's connection limit.
 *
 * Neon requires TLS. sslmode in the connection string is not reliably honoured
 * by node-postgres, so TLS is set explicitly when the host looks like Neon.
 */
const connectionString = process.env.DATABASE_URL

const globalForPg = globalThis as unknown as { _pgPool?: Pool }

export const pool =
  globalForPg._pgPool ??
  new Pool({
    connectionString,
    ssl:
      connectionString && /neon\.tech|sslmode=require/.test(connectionString)
        ? { rejectUnauthorized: false }
        : undefined,
    max: 3,
    idleTimeoutMillis: 30_000,
  })

if (process.env.NODE_ENV !== "production") globalForPg._pgPool = pool
