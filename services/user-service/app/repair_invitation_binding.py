"""Repair one legacy joined invitation from the original authenticated provisioner commit."""

import argparse
import json
import os
import re
import sys

import firebase_admin
import google.auth
from firebase_admin import auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore

from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.identity import owner_key

from .account_erasure import verified_subject
from .invitation_erasure import InvitationReviewRequired
from .workspace_invitations import INVITATIONS, MEMBERS, invitation_id


def audit_commit(project, entry_id, writer):
    if (
        not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project)
        or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", entry_id)
        or not re.fullmatch(
            r"[a-z][a-z0-9-]{4,28}[a-z0-9]@" + re.escape(project) + r"\.iam\.gserviceaccount\.com",
            writer,
        )
    ):
        raise InvitationReviewRequired
    log = f"projects/{project}/logs/cloudaudit.googleapis.com%2Fdata_access"
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/logging.read"])
    with AuthorizedSession(credentials) as session:
        response = session.post(
            "https://logging.googleapis.com/v2/entries:list",
            json={
                "resourceNames": ["projects/" + project],
                "filter": f'logName="{log}" AND insertId="{entry_id}"',
                "pageSize": 2,
            },
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
    if body.get("nextPageToken") or len(body.get("entries", [])) != 1:
        raise InvitationReviewRequired
    entry = body["entries"][0]
    audit = entry.get("protoPayload", {})
    if (
        entry.get("logName") != log
        or entry.get("insertId") != entry_id
        or audit.get("@type") != "type.googleapis.com/google.cloud.audit.AuditLog"
        or audit.get("methodName") != "google.firestore.v1.Firestore.Commit"
        or audit.get("serviceName") != "firestore.googleapis.com"
        or audit.get("status", {}).get("code", 0) != 0
        or audit.get("authenticationInfo", {}).get("principalEmail") != writer
    ):
        raise InvitationReviewRequired
    return audit


def original_binding(project, database, subject, audit):
    prefix = f"projects/{project}/databases/{database}"
    request = audit.get("request", {})
    writes = request.get("writes", [])
    if (
        request.get("database") != prefix
        or request.get("@type") != "type.googleapis.com/google.firestore.v1.CommitRequest"
        or len(writes) != 2
        or not all(
            "update" in write and not (write.keys() & {"transform", "delete", "updateMask"})
            for write in writes
        )
    ):
        raise InvitationReviewRequired
    rows = {write["update"]["name"]: write["update"]["fields"] for write in writes}
    member_path = prefix + "/documents/" + MEMBERS + "/" + owner_key(subject.uid)
    member = rows.pop(member_path, {})
    if (
        member.get("googleSubject") != {"stringValue": subject.google_subject}
        or member.get("state") != {"stringValue": "active"}
        or len(rows) != 1
    ):
        raise InvitationReviewRequired
    path, invitation = next(iter(rows.items()))
    joined = member.get("joinedAt", {}).get("integerValue")
    email = invitation.get("email", {}).get("stringValue")
    delivery = invitation.get("deliveryKey", {}).get("stringValue")
    if (
        not isinstance(email, str)
        or not email.isascii()
        or not re.fullmatch(r"[a-z0-9]+(?:\.[a-z0-9]+)*@gmail\.com", email)
        or path != prefix + "/documents/" + INVITATIONS + "/" + invitation_id(email)
        or invitation.get("status") != {"stringValue": "joined"}
        or not isinstance(delivery, str)
        or not re.fullmatch(r"workspace-invite/[a-f0-9]{32}", delivery)
        or not isinstance(joined, (str, int))
        or not str(joined).isdecimal()
        or int(joined) < 1
        or str(invitation.get("updatedAt", {}).get("integerValue")) != str(joined)
    ):
        raise InvitationReviewRequired
    return email, delivery, int(joined)


def repair(client, subject, evidence, *, apply):
    email, revision, joined = evidence
    owner = owner_key(subject.uid)
    invite = client.collection(INVITATIONS).document(invitation_id(email))
    member = client.collection(MEMBERS).document(owner)

    @firestore.transactional
    def link(transaction):
        row = invite.get(transaction=transaction).to_dict()
        membership = member.get(transaction=transaction).to_dict()
        if (
            row is None
            or row.get("status") != "joined"
            or row.get("email") != email
            or row.get("deliveryKey") != revision
            or row.get("updatedAt") != joined
            or row.get("joinedOwner", owner) != owner
            or row.get("joinedGoogleSubject", subject.google_subject) != subject.google_subject
        ):
            raise InvitationReviewRequired
        if membership is not None and (
            membership.get("googleSubject") != subject.google_subject
            or membership.get("joinedAt") != joined
            or membership.get("invitationId", invite.id) != invite.id
        ):
            raise InvitationReviewRequired
        if apply and ("joinedOwner" not in row or "joinedGoogleSubject" not in row):
            transaction.update(
                invite, {"joinedOwner": owner, "joinedGoogleSubject": subject.google_subject}
            )
        if apply and membership is not None and "invitationId" not in membership:
            transaction.update(member, {"invitationId": invite.id})

    link(client.transaction())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True, choices=["user-data", "(default)"])
    parser.add_argument("--writer-service-account", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or os.getenv("FIRESTORE_EMULATOR_HOST"):
        parser.error("Use the original cloud audit and identity authority for this operation.")
    try:
        case = strict_json_loads(sys.stdin.buffer.read(2049), max_bytes=2048)
        if set(case) != {"uid", "email", "insertId"}:
            raise InvitationReviewRequired
        app = firebase_admin.initialize_app(options={"projectId": args.project})
        record = auth.get_user(case["uid"], app=app)
        if record.uid != case["uid"]:
            raise InvitationReviewRequired
        subject = verified_subject(record, case["email"], apply=False)
        audit = audit_commit(args.project, case["insertId"], args.writer_service_account)
        evidence = original_binding(args.project, args.database, subject, audit)
        client = firestore.Client(project=args.project, database=args.database)
        try:
            repair(client, subject, evidence, apply=args.apply)
        finally:
            client.close()
    except Exception:
        parser.exit(
            1, "Original admission or current scope unverified. Keep the case under review.\n"
        )
    print(json.dumps({"scope": "user.invitation_binding", "verified": True, "applied": args.apply}))


if __name__ == "__main__":
    main()
