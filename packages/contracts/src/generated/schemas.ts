export const messageEnvelopeSchema = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.kairo.dev/v1/message-envelope.schema.json",
  "title": "Kairo message envelope v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "messageId",
    "type",
    "schemaVersion",
    "createdAt",
    "payload"
  ],
  "properties": {
    "messageId": {
      "$ref": "#/$defs/uuid"
    },
    "type": {
      "$ref": "#/$defs/namespacedType"
    },
    "schemaVersion": {
      "const": "1.0.0"
    },
    "createdAt": {
      "$ref": "#/$defs/utcTimestamp"
    },
    "correlationId": {
      "$ref": "#/$defs/uuid"
    },
    "causationId": {
      "$ref": "#/$defs/uuid"
    },
    "sender": {
      "$ref": "#/$defs/participant"
    },
    "recipient": {
      "$ref": "#/$defs/participant"
    },
    "payload": {
      "type": "object"
    }
  },
  "$defs": {
    "uuid": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "utcTimestamp": {
      "type": "string",
      "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z$"
    },
    "namespacedType": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9]*(\\.[a-z0-9]+)+$"
    },
    "participant": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id",
        "kind"
      ],
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1
        },
        "kind": {
          "type": "string",
          "minLength": 1
        }
      }
    }
  }
} as const;

export const eventEnvelopeSchema = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.kairo.dev/v1/event-envelope.schema.json",
  "title": "Kairo event envelope v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "eventId",
    "type",
    "schemaVersion",
    "occurredAt",
    "source",
    "payload"
  ],
  "properties": {
    "eventId": {
      "$ref": "#/$defs/uuid"
    },
    "type": {
      "$ref": "#/$defs/namespacedType"
    },
    "schemaVersion": {
      "const": "1.0.0"
    },
    "occurredAt": {
      "$ref": "#/$defs/utcTimestamp"
    },
    "correlationId": {
      "$ref": "#/$defs/uuid"
    },
    "causationId": {
      "$ref": "#/$defs/uuid"
    },
    "source": {
      "$ref": "#/$defs/source"
    },
    "payload": {
      "type": "object"
    }
  },
  "$defs": {
    "uuid": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "utcTimestamp": {
      "type": "string",
      "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z$"
    },
    "namespacedType": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9]*(\\.[a-z0-9]+)+$"
    },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "component"
      ],
      "properties": {
        "component": {
          "type": "string",
          "minLength": 1
        },
        "instanceId": {
          "type": "string",
          "minLength": 1
        }
      }
    }
  }
} as const;
