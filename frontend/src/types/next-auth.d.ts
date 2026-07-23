import "next-auth"
import "next-auth/jwt"

/**
 * Carry the account id and its tenant id through the session and JWT, so the
 * app can send the correct X-Tenant-Id for a signed-in user.
 */
declare module "next-auth" {
  interface Session {
    user: {
      id?: string
      tenantId?: string
      name?: string | null
      email?: string | null
      image?: string | null
    }
  }

  interface User {
    tenantId?: string
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    uid?: string
    tenantId?: string
  }
}
