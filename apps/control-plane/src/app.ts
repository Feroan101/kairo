import swagger from "@fastify/swagger";
import { Type } from "@sinclair/typebox";
import Fastify, { type FastifyInstance } from "fastify";
import { loadServerConfig, type ServerConfig } from "./config.ts";
import { checkDatabaseConnection, type Database } from "./db/client.ts";
import { registerErrorHandling } from "./errors.ts";
import { authRoutes } from "./identity/auth-routes.ts";
import { createAuthenticationHook } from "./identity/authorization.ts";
import { organizationRoutes } from "./identity/organization-routes.ts";

export interface AppOptions {
  serverConfig?: ServerConfig;
  logger?: boolean;
}

export async function createApp(
  database: Database,
  options: AppOptions = {},
): Promise<FastifyInstance> {
  const serverConfig = options.serverConfig ?? loadServerConfig();
  const app = Fastify({
    bodyLimit: 16 * 1024,
    logger:
      options.logger === false
        ? false
        : {
            level: serverConfig.logLevel,
            redact: ["req.headers.authorization", "req.body.password", "res.headers.set-cookie"],
          },
  });

  registerErrorHandling(app);
  app.addHook("preHandler", createAuthenticationHook(database));

  await app.register(swagger, {
    openapi: {
      openapi: "3.1.0",
      info: {
        title: "Kairo Control Plane API",
        version: "0.1.0",
        description: "Identity, access, and agent management API for Kairo.",
      },
      components: {
        securitySchemes: {
          bearerAuth: {
            type: "http",
            scheme: "bearer",
            bearerFormat: "opaque",
          },
        },
      },
    },
  });

  app.get("/openapi.json", { config: { public: true } }, async () => app.swagger({ yaml: false }));

  app.get(
    "/health",
    {
      config: { public: true },
      schema: {
        response: {
          200: Type.Object({ status: Type.Literal("ok") }, { additionalProperties: false }),
        },
      },
    },
    async () => {
      await checkDatabaseConnection(database);
      return { status: "ok" as const };
    },
  );

  await app.register(authRoutes, { database, serverConfig });
  await app.register(organizationRoutes, { database });

  return app;
}
