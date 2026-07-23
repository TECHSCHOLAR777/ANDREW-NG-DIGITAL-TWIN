import { NextResponse } from "next/server"
import bcrypt from "bcryptjs"

import { pool } from "@/lib/db"

/**
 * Create a credential account and bind it to a tenant.
 *
 * If the caller passes the anonymous tenant their browser was already using,
 * and that tenant exists and is not yet claimed by another account, the account
 * adopts it so context built as a guest is preserved. Otherwise a fresh tenant
 * is created. The password is stored only as a bcrypt hash; the optional
 * context is a short free-text note, never a credential.
 */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export async function POST(req: Request) {
  let body: {
    email?: string
    password?: string
    name?: string
    context?: string
    anonTenantId?: string
  }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 })
  }

  const email = (body.email ?? "").trim()
  const password = body.password ?? ""
  const name = (body.name ?? "").trim() || null
  const context = (body.context ?? "").trim().slice(0, 600) || null

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json(
      { error: "Enter a valid email address." },
      { status: 400 }
    )
  }
  if (password.length < 8) {
    return NextResponse.json(
      { error: "Use a password of at least 8 characters." },
      { status: 400 }
    )
  }

  const client = await pool.connect()
  try {
    const existing = await client.query(
      "SELECT 1 FROM app_users WHERE email_lower = $1 LIMIT 1",
      [email.toLowerCase()]
    )
    if (existing.rowCount) {
      return NextResponse.json(
        { error: "An account with that email already exists." },
        { status: 409 }
      )
    }

    const passwordHash = await bcrypt.hash(password, 10)

    await client.query("BEGIN")

    // Adopt the anonymous tenant when it exists and is unclaimed.
    let tenantId: string | null = null
    const anon = body.anonTenantId
    if (anon && UUID_RE.test(anon)) {
      const t = await client.query("SELECT 1 FROM tenants WHERE id = $1", [anon])
      const claimed = await client.query(
        "SELECT 1 FROM app_users WHERE tenant_id = $1 LIMIT 1",
        [anon]
      )
      if (t.rowCount && !claimed.rowCount) tenantId = anon
    }
    if (!tenantId) {
      const created = await client.query(
        "INSERT INTO tenants (name) VALUES ($1) RETURNING id",
        [name ?? "Digital Twin User"]
      )
      tenantId = created.rows[0].id as string
    }

    await client.query(
      `INSERT INTO app_users (email, password_hash, name, tenant_id, context)
       VALUES ($1, $2, $3, $4, $5)`,
      [email, passwordHash, name, tenantId, context]
    )

    await client.query("COMMIT")
    return NextResponse.json({ ok: true })
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {})
    console.error("signup failed:", err)
    return NextResponse.json(
      { error: "Could not create the account. Please try again." },
      { status: 500 }
    )
  } finally {
    client.release()
  }
}
