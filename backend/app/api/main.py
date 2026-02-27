"""FastAPI application for ProspectIQ API.

Serves the Next.js CRM dashboard with endpoints for
companies, approvals, pipeline agents, analytics, and webhooks.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import companies, approvals, pipeline, analytics, webhooks

app = FastAPI(
    title="ProspectIQ API",
    version="1.0.0",
    description="AI-powered manufacturing sales prospecting backend",
)

# CORS — allow Next.js dev server, Vercel, and Netlify domains
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://localhost:3000$|^https://.*\.vercel\.app$|^https://.*\.netlify\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount route modules
app.include_router(companies.router)
app.include_router(approvals.router)
app.include_router(pipeline.router)
app.include_router(analytics.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok", "service": "prospectiq-api"}
