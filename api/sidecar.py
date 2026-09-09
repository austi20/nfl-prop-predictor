from __future__ import annotations

import argparse
import multiprocessing
import os

# The fantasy-slate build fans out across processes; keep each worker's BLAS
# single-threaded so 11 workers do not oversubscribe a 16-core box. Must be set
# before NumPy is imported anywhere in this process or its spawned children.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import uvicorn


def main() -> None:
    # PyInstaller onefile + multiprocessing spawn: a re-launched child must run
    # the mp bootstrap and exit here, never fall through to uvicorn.
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="Run the NFL Prop Predictor FastAPI sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()

    from api.server import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
