from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.langfuse_observability import flush_langfuse
from core.observability import setup_observability

# Create FastAPI app
app = FastAPI()

# CORS Middleware (adjust for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

# Routers
from api.health import router as health_router
from api.upload import router as upload_router
from api.profile import router as profile_router
from api.image_crud import router as image_crud_router
from api.metadata import router as metadata_router
from api.export import router as export_router
from api.supplier import router as supplier_router

# Register routers
app.include_router(health_router)
app.include_router(upload_router)
app.include_router(profile_router)
app.include_router(image_crud_router)
app.include_router(metadata_router)
app.include_router(export_router)
app.include_router(supplier_router)

# Enable tracing when OTEL_ENABLED=true
setup_observability(app)


@app.get("/")
async def root():
    return {"message": "API is running"}

@app.get("/api/health", tags=["System"])
async def health_check():
    return {"status": "ok"}


@app.on_event("shutdown")
async def shutdown_langfuse() -> None:
    flush_langfuse()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_fastapi_app:app", host="0.0.0.0", port=8000, reload=True)
