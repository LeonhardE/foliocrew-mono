"""Serve an isolated verification image with the same Firebase function handlers."""

from flask import Flask, request
from main import before_workspace_user_created, before_workspace_user_signed_in

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "workspace-admission"}


@app.post("/before-create")
def before_create():
    return before_workspace_user_created(request)


@app.post("/before-sign-in")
def before_sign_in():
    return before_workspace_user_signed_in(request)
