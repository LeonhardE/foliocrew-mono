// Synthetic public DTOs and names produced by the actual unchanged Owner crypto.
const { createHash } = require("node:crypto");
const flow = require("./full-flow-crypto-fixture.cjs");
const { compile, catalogue } = require("./resource-library-helpers.cjs");
const contract = compile("../lib/resource-display.ts");
const C = "folioview.agent-workspace.v2.0",
  P = "folioview.private-display-name.v1";
async function fixture(uid = "a") {
  const runtime = await flow.createHarness();
  try {
    const owner = await flow.createOwner(runtime, uid),
      sources = [flow.bindings()[0]];
    const prepared = await owner.session.prepareDisplayName({
      ref: sources[0].ref,
      item: null,
      name: "Synthetic alias",
    });
    const command = prepared.body.command,
      payload = flow.decoded(command);
    const item = {
      command,
      state: {
        ...Object.fromEntries(
          ["contractVersion", "profile", "ownerSubject", "vaultId", "rootKeyId", "ref"].map((k) => [
            k,
            payload[k],
          ]),
        ),
        revision: payload.revision,
        stableOperationId: payload.stableOperationId,
        operationFingerprint: createHash("sha256")
          .update(command.protected + "." + command.payload)
          .digest("hex"),
        recipientKeyId: payload.recipientKeyId,
        acceptedAt: owner.now(),
      },
    };
    const rows = sources.map(({ ref, sourceEpoch }) => ({ resourceRef: ref, sourceEpoch }));
    const authority = await owner.session.taskAuthority(null);
    const scope = {
      ownerSubject: owner.owner,
      vaultId: owner.vault.vaultId,
      rootKeyId: owner.vault.rootKeyId,
      version: owner.vault.version,
      registrySequence: authority.registrySequence,
      checkpointDigest: authority.checkpointDigest,
      keyEpoch: authority.keyEpoch,
    };
    const state = {
      owner: uid + ":1",
      uid,
      generation: 1,
      session: owner.session,
      eligible: true,
      vault: owner.vault,
      sources: rows,
      proof: null,
    };
    const snapshot = contract.resourceDisplaySnapshot(state.vault);
    await owner.session.acceptVault(snapshot.vault);
    state.vault = snapshot.vault;
    state.proof = await contract.verifiedDisplayVault(
      snapshot,
      rows,
      state.owner,
      uid,
      state.generation,
      state.session,
    );
    const list = catalogue();
    list.groups[0].items[0].ref = structuredClone(rows[0].resourceRef);
    const body = () =>
      structuredClone({
        contractVersion: C,
        profile: "folioview.owner-resource-display.v1",
        mode: "full",
        scope,
        catalogue: list,
        displayNameCapabilities: {
          contractVersion: C,
          profile: P,
          enabled: true,
          maxSources: 10,
          maxNameLength: 80,
        },
        displayNames: { contractVersion: C, profile: P, items: [item] },
      });
    return { runtime, owner, state, scope, item, body, contract, close: () => runtime.close() };
  } catch (error) {
    await runtime.close();
    throw error;
  }
}
module.exports = { fixture, contract, C, P };
