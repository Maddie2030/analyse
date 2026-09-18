import type { FastifyRequest } from "fastify";
import type { Redis } from "ioredis";

export type SessionUser = {
  version: number;
  user_id: string;
  username: string;
  role: string;
  is_active: boolean;
  created_at?: string;
};

const SESSION_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function validSessionShape(value: SessionUser): boolean {
  const version = value.version;
  if (version !== 1) return false;
  if (!value.user_id || !value.username || value.username.length > 100) return false;
  if (value.role !== "user" && value.role !== "admin") return false;
  if (value.is_active !== true) return false;
  if (!SESSION_UUID.test(value.user_id)) return false;
  if (!value.created_at || !RFC3339.test(value.created_at) || Number.isNaN(Date.parse(value.created_at))) return false;
  return true;
}

export async function sessionFromRequest(
  request: FastifyRequest,
  redis: Redis,
  cookieName: string,
): Promise<SessionUser | null> {
  const sessionId = request.cookies[cookieName];
  if (!sessionId) return null;

  const raw = await redis.get(`session:${sessionId}`);
  if (!raw) return null;

  try {
    const value = JSON.parse(raw) as SessionUser;
    return validSessionShape(value) ? value : null;
  } catch {
    return null;
  }
}

export async function requireUser(
  request: FastifyRequest,
  redis: Redis,
  cookieName: string,
): Promise<SessionUser> {
  const user = await sessionFromRequest(request, redis, cookieName);
  if (!user) {
    const err = new Error("Not authenticated.") as Error & { statusCode?: number };
    err.statusCode = 401;
    throw err;
  }
  return user;
}

export async function requireAdmin(
  request: FastifyRequest,
  redis: Redis,
  cookieName: string,
): Promise<SessionUser> {
  const user = await requireUser(request, redis, cookieName);
  if (user.role !== "admin") {
    const err = new Error("Admin access required.") as Error & { statusCode?: number };
    err.statusCode = 403;
    throw err;
  }
  return user;
}
