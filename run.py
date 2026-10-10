import uvicorn
from app.core.config import local_config


service_config = local_config.get("service", {})

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=service_config.get("host", "0.0.0.0"),
        port=int(service_config.get("port", 8000)),
    )
