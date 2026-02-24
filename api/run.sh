#!/bin/bash

PATH=$PATH:$LAMBDA_TASK_ROOT/bin \
    PYTHONPATH=$PYTHONPATH:/opt/python:$LAMBDA_RUNTIME_DIR:$LAMBDA_TASK_ROOT/src \
    exec python -m uvicorn --port=$PORT api.app:app
