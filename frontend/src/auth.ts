import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import bcrypt from "bcryptjs"

import { pool } from "@/lib/db"

/**
 * Authentication (Auth.js v5, Credentials provider, JWT sessions).
 *
 * JWT sessions mean no adapter tables: the only persisted record is the
 * credential user row (migration 016), and the tenant the account owns rides in
 * the token. Every existing tenant-scoped API call keeps working; auth only
 * decides which tenant id the client sends.
 *
 * authorize() verifies the password against the stored bcrypt hash and returns
 * the account plus its tenant id. Any failure returns null, which Auth.js
 * surfaces as an invalid-credentials error without leaking whether the email
 * exists.
 */
export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  trustHost: true,
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      authorize: async (credentials) => {
        const email = String(credentials?.email ?? "").trim().toLowerCase()
        const password = String(credentials?.password ?? "")
        if (!email || !password) return null

        const { rows } = await pool.query(
          `SELECT id, email, name, password_hash, tenant_id
             FROM app_users
            WHERE email_lower = $1
            LIMIT 1`,
          [email]
        )
        const user = rows[0]
        if (!user) return null

        const ok = await bcrypt.compare(password, user.password_hash)
        if (!ok) return null

        return {
          id: user.id as string,
          email: user.email as string,
          name: (user.name as string | null) ?? undefined,
          tenantId: user.tenant_id as string,
        }
      },
    }),
  ],
  callbacks: {
    jwt: async ({ token, user }) => {
      if (user) {
        token.uid = user.id
        token.tenantId = (user as { tenantId?: string }).tenantId
      }
      return token
    },
    session: async ({ session, token }) => {
      if (session.user) {
        session.user.id = token.uid as string
        session.user.tenantId = token.tenantId as string
      }
      return session
    },
  },
})
