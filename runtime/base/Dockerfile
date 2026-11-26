FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/usr/local/bin:${PATH}" \
    VIRTUAL_ENV=/app/harness/kairo_harness/.venv

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /usr/local/bin/

WORKDIR /app

RUN groupadd --gid 10001 kairo \
    && useradd --uid 10001 --gid kairo --create-home --shell /usr/sbin/nologin kairo

COPY harness/kairo_harness/pyproject.toml harness/kairo_harness/uv.lock ./harness/kairo_harness/
COPY harness/kairo_harness/src ./harness/kairo_harness/src
COPY packages/contracts/schemas ./packages/contracts/schemas

RUN uv sync --project harness/kairo_harness --frozen --no-dev --no-editable \
    && chown -R kairo:kairo /app

USER kairo

ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

ENTRYPOINT ["python", "-m", "kairo_harness"]
CMD ["--provider", "mock", "--task", "Confirm that the standalone Kairo harness is running."]
