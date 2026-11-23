"""Authenticated native bootstrap for personal host-owned credentials.

OAuth associates the public setup with a preregistered provider. It cannot read
financial resources, mint Agent keys, or grant/recover execution authority.
"""

from urllib.parse import urlsplit

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.schema import safe_https_url

from .agent_credentials import AgentCredentialService, operation_path
from .native_transport import NativeUnit
from .persistent_agents import snapshot, stored_identity
from .store import StoreUnavailable

CONNECTION_INSTRUCTIONS = (
    "When the user asks to connect Foliocrew, continue onboarding after account linking. "
    "Use agent_connection to check the current credential. If setup is needed, call "
    "prepare_agent_authorization, use the verified Foliocrew client on this Agent's private "
    "host, and submit the encrypted offer. Ask the user only to open the Foliocrew approval "
    "link and review their access. After approval, use agent_activation and the same client "
    "to validate and install the credential before reporting the connection ready."
)


class NativeCredentialService:
    def __init__(self, native, *, owner_url):
        if (
            not safe_https_url(owner_url)
            or urlsplit(owner_url).path != "/agents"
            or urlsplit(owner_url).query
            or urlsplit(owner_url).fragment
        ):
            raise ContractError("authorization_unavailable")
        self.native, self.store, self.owner_url = native, native.store, owner_url
        self.credentials = AgentCredentialService(
            self.store,
            audience=native.config.base.issuer,
            client_ids=[c.client_id for c in native.config.clients],
            clock=native.clock,
            user_vaults=native.user_vaults,
        )

    def _principal(self, token):
        return self.native.authenticate(token)

    def _user_scope(self, token):
        if self.credentials.user_vaults.owner is None:
            return None
        return self.credentials._native_user_scope(self._principal(token))

    def _context(self, token):
        user_scope = self._user_scope(token)

        def read(unit):
            p = self.native.principal(NativeUnit(unit, self.native.config.resource), token)
            owner, _, _, conn = self.credentials._native(unit, p, user_scope)
            state = self.credentials._credential_state(
                unit, owner, p.vault_id, p.connection_id, conn
            )
            return p, conn, state

        return self.store.transact(read)

    def inspect(self, token):
        p, conn, state = self._context(token)
        from .agent_client_assets import client_metadata

        lease = state["lease"]
        return {
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.agent-credential.v1",
            "issuer": self.native.config.base.issuer,
            "provider": conn["provider"],
            "client": client_metadata(),
            "actor": {
                "ownerSubject": p.owner_subject,
                "vaultId": p.vault_id,
                "connectionId": p.connection_id,
                "clientId": p.client_id,
            },
            "credentialStatus": state["status"],
            "credentialExpiresAt": None if lease is None else lease["expiresAt"],
            "hostInstructions": (
                CONNECTION_INSTRUCTIONS
                + " Keep credentials only in this Agent's private persistent directory. "
                "Load the existing profile for every later task. If missing, corrupt, expired "
                "or rejected, stop and tell the user to authorize again in Foliocrew. "
                "Never print private keys, upload credentials, or silently replace active keys. "
                "Use the reviewed local client for PoP requests, local ciphertext decryption "
                "and Owner-encrypted reports. Native OAuth is bootstrap only."
            ),
        }

    def prepare(self, token):
        p = self._principal(token)
        setup = self.credentials.begin_setup(p)
        context = self.inspect(token)
        return {**context, "setup": setup, "ownerUrl": self.owner_url}

    def offer(self, token, intent, packet):
        p = self._principal(token)
        setup = self.credentials.put_offer(p, intent, packet)
        return {"setupIntentId": setup["setupIntentId"], "state": "awaiting_owner_approval"}

    def activation(self, token, intent):
        user_scope = self._user_scope(token)

        def read(unit):
            p = self.native.principal(NativeUnit(unit, self.native.config.resource), token)
            owner, _, _, conn = self.credentials._native(unit, p, user_scope)
            setup = self.credentials._setup(
                unit, intent, owner, p.vault_id, p.connection_id, conn, live=False
            )
            if setup["authorizationId"] != p.authorization_id:
                raise ContractError("key_authorization_required")
            operation = setup["consumedBy"]
            if operation is None:
                return {
                    "setupIntentId": intent,
                    "state": "awaiting_owner_approval",
                    "activation": None,
                }
            saved = unit.get(operation_path(owner, p.vault_id, operation))
            if saved is None:
                raise StoreUnavailable
            receipt = self.credentials._receipt(
                saved, owner, p.vault_id, p.connection_id, operation
            )
            current = stored_identity(unit, owner, p.vault_id, p.connection_id)
            if (
                current is None
                or current.get("credentialLease", {}).get("credentialFingerprint")
                != receipt["fingerprint"]
            ):
                raise ContractError("key_authorization_required")
            return {
                "setupIntentId": intent,
                "state": "approved",
                "activation": snapshot(saved["command"].get("activation")),
            }

        return self.store.transact(read)
