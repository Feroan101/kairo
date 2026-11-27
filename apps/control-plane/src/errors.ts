import type { FastifyError, FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

export class HttpError extends Error {
  constructor(
    readonly statusCode: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export function unauthorized(message = "Authentication required"): HttpError {
  return new HttpError(401, "UNAUTHORIZED", message);
}

export function forbidden(message = "Insufficient permissions"): HttpError {
  return new HttpError(403, "FORBIDDEN", message);
}

export function notFound(message = "Resource not found"): HttpError {
  return new HttpError(404, "NOT_FOUND", message);
}

export function conflict(message = "Resource conflict"): HttpError {
  return new HttpError(409, "CONFLICT", message);
}

export function sendError(reply: FastifyReply, statusCode: number, code: string, message: string) {
  return reply.code(statusCode).send({ error: { code, message } });
}

export function registerErrorHandling(app: FastifyInstance): void {
  app.setErrorHandler((error: FastifyError, request, reply) => {
    if (error instanceof HttpError) {
      sendError(reply, error.statusCode, error.code, error.message);
      return;
    }

    if (error.validation) {
      sendError(reply, 400, "VALIDATION_ERROR", "Invalid request");
      return;
    }

    if (error.statusCode && error.statusCode >= 400 && error.statusCode < 500) {
      sendError(reply, error.statusCode, "REQUEST_ERROR", error.message);
      return;
    }

    request.log.error({ err: error }, "Unhandled control-plane error");
    sendError(reply, 500, "INTERNAL_ERROR", "Internal server error");
  });

  app.setNotFoundHandler((_request: FastifyRequest, reply: FastifyReply) => {
    sendError(reply, 404, "NOT_FOUND", "Route not found");
  });
}
