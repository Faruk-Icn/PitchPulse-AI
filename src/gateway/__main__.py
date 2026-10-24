"""Start the local gateway on loopback; configure ingress separately."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("src.gateway.app:app", host="127.0.0.1", port=8000)
