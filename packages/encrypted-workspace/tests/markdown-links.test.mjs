/** Compare exact captures with the previous policy, including ordering and duplicates. */
import assert from "node:assert/strict";
import test from "node:test";
import { markdownDestinations } from "../src/markdown-links.mjs";
import * as core from "../dist/core.mjs";

function previousDestinations(text) {
  return [
    ...[...text.matchAll(/\]\(\s*(<[^>]+>|[^\s)]+)/g)].map((m) => m[1]),
    ...[...text.matchAll(/^\s*\[[^\]]+\]:\s*(\S+)/gm)].map((m) => m[1]),
    ...[...text.matchAll(/<([^<>\s]+:[^<>\s]*)>/g)].map((m) => m[1]),
  ];
}

test("destination captures retain precedence, fallback, duplicates and group order", () => {
  const cases = [
    "",
    "](https://a.example/path) <https://b.example/path>",
    "](<https://a.example/a b>) ](<) ](<>) ]()",
    "](<https://a.example/a)b>) ](https://b.example/)",
    "[a]: https://a.example/\n[b]: https://b.example/",
    "\n\n\t[a\nlabel]:\n\t https://a.example/\r\n[b]: <https://b.example/>",
    "[]: https://a.example/\n[a]x]: https://b.example/",
    "<:> <::> <a:> <:a:> <a:b:c> <a:<b:c>>",
    "[a]: https://a.example/\n](https://a.example/) <https://a.example/>",
    "\r\n\u2028\u2029\ufeff[a]:\u00a0https://a.example/",
    "[a]: \n [b]: \n https://a.example/",
    "😀 ](<https://a.example/😀>)\n[😀]: https://a.example/😀",
  ];
  for (const text of cases)
    assert.deepEqual(markdownDestinations(text), previousDestinations(text));
});

test("generated bounded Markdown preserves all original captures", () => {
  let state = 0x6f6c696f;
  const random = (limit) => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) % limit;
  };
  const parts = [
    "](",
    "<",
    ">",
    ")",
    "[",
    "]",
    ":",
    "a",
    "-",
    "/",
    "https://a.example/",
    " ",
    "\t",
    "\n",
    "\r",
    "\r\n",
    "\v",
    "\f",
    "\u00a0",
    "\ufeff",
    "\u2028",
    "\u2029",
    "😀",
  ];
  for (let i = 0; i < 20000; i++) {
    const text = Array.from({ length: random(80) }, () => parts[random(parts.length)]).join("");
    assert.deepEqual(markdownDestinations(text), previousDestinations(text), JSON.stringify(text));
  }
});

test("maximum bounded failing prefixes and multiline runs keep the original captures", () => {
  for (const text of [
    "](<)".repeat(4096),
    "<a:" + "a:".repeat(8190),
    "\n".repeat(16384),
    "[\n".repeat(8192),
    "\r\n".repeat(8192),
    "\u2028".repeat(16384),
    " ".repeat(16380) + "[a]:",
  ])
    assert.deepEqual(markdownDestinations(text), previousDestinations(text));
});

function previousMarkdownAllowed(value) {
  const named = {
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    colon: ":",
    Tab: "\t",
    NewLine: "\n",
  };
  let text = value;
  try {
    for (let count = 0; count < 4; count++) {
      const decoded = text.replace(/&(#x[0-9a-f]+|#\d+|[A-Za-z][A-Za-z0-9]+);?/gi, (_, code) => {
        if (code[0] !== "#") {
          if (!Object.hasOwn(named, code)) throw new Error("refuse");
          return named[code];
        }
        const point = /^#x/i.test(code) ? parseInt(code.slice(2), 16) : Number(code.slice(1));
        if (
          !Number.isSafeInteger(point) ||
          point <= 0 ||
          point > 0x10ffff ||
          (point >= 0xd800 && point <= 0xdfff)
        )
          throw new Error("refuse");
        return String.fromCodePoint(point);
      });
      if (decoded === text) break;
      text = decoded;
      if (count === 3 && /&(?:#x[0-9a-f]+|#\d+|[A-Za-z][A-Za-z0-9]+);?/i.test(text))
        throw new Error("refuse");
    }
    if (/<\s*(?:\/?[A-Za-z][A-Za-z0-9-]*(?:\s|\/?>)|!|\?)/.test(text) || /!\s*\[/.test(text))
      return false;
    return previousDestinations(text).every((x) => core.safeUrl(x.replace(/^<|>$/g, "")));
  } catch {
    return false;
  }
}
const report = (markdown) => ({
  title: "Synthetic report",
  summary: "Offline validation only",
  sections: [{ sectionId: "main", markdown }],
  citations: [],
  limitations: [],
});
function accepted(text) {
  try {
    core.resultContent(report(text), { sections: [{ sectionId: "main" }] });
    return true;
  } catch (error) {
    assert.equal(error.code, "private_schema_invalid");
    return false;
  }
}

test("actual result acceptance retains entities, HTML refusal and HTTPS policy", () => {
  const cases = [
    "ordinary report",
    "](https://a.example/) <https://b.example/>",
    "[a]:\n https://a.example/",
    "](<https://a.example/a b>)",
    "](javascript:alert(1))",
    "](http://a.example/)",
    "](https://user:password@a.example/)",
    "<script>bad</script>",
    "![image](https://a.example/)",
    "&lt;script&gt;bad",
    "&#x3c;https://a.example/&#x3e;",
    "&unknown;",
    "&#0;",
    "&#xD800;",
    "&amp;amp;amp;lt;script&gt;",
    "&amp;amp;amp;amp;lt;script&gt;",
    "\r\n\u2028[a]:\ufeffhttps://a.example/",
    "<a:" + "a:".repeat(8190),
    "\n".repeat(16384),
    "[\n".repeat(8192),
    "](<)".repeat(4096),
  ];
  for (const text of cases) assert.equal(accepted(text), previousMarkdownAllowed(text));
  let state = 0x6d61726b;
  const parts = [
    "](",
    "<",
    ">",
    ")",
    "[",
    "]",
    ":",
    "a",
    "https://a.example/",
    " ",
    "\n",
    "\r",
    "\u00a0",
    "\u2028",
    "&amp;",
    "&lt;",
    "&colon;",
    "&#x3c;",
    "&unknown;",
    "😀",
    "![",
  ];
  for (let i = 0; i < 5000; i++) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const size = state % 60;
    let text = "";
    for (let j = 0; j < size; j++) {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      text += parts[state % parts.length];
    }
    assert.equal(accepted(text), previousMarkdownAllowed(text), JSON.stringify(text));
  }
});

test("character and section limits retain their original exact boundaries", () => {
  for (const text of ["a".repeat(16384), "😀".repeat(16384)])
    core.resultContent(report(text), { sections: [{ sectionId: "main" }] });
  assert.throws(() => core.resultContent(report("a".repeat(16385)), { sections: [] }), {
    code: "invalid_schema",
  });
  const value = report("");
  value.sections = Array.from({ length: 8 }, (_, i) => ({ sectionId: "s" + i, markdown: "" }));
  core.resultContent(value, { sections: value.sections });
  value.sections.push({ sectionId: "ninth", markdown: "" });
  assert.throws(() => core.resultContent(value, { sections: value.sections }), {
    code: "invalid_schema",
  });
});

test("typed facade adds only the pure collector and rejects non-strings without coercion", () => {
  const previousExports = [
    "AGENT_CREDENTIAL_PROFILE",
    "BINDING",
    "CONSENT_PROFILE",
    "CONTRACT",
    "CREDENTIAL_NOTICE_SECONDS",
    "DEFAULT_CREDENTIAL_SECONDS",
    "JWE_HEADER",
    "PROFILE",
    "Registry",
    "RuntimeDenied",
    "applyConsent",
    "approveCredential",
    "array",
    "bytes",
    "canonical",
    "context",
    "createRegistryCertificateVerifier",
    "credentialStatus",
    "deny",
    "digest",
    "digestString",
    "exact",
    "fingerprint",
    "identifier",
    "inspect",
    "integer",
    "jose",
    "keyId",
    "matchBinding",
    "object",
    "open",
    "parsed",
    "permissionFor",
    "privatePayload",
    "publicKey",
    "reference",
    "requestProof",
    "requireCurrentCredential",
    "resultContent",
    "safeUrl",
    "same",
    "seal",
    "shape",
    "sign",
    "unique",
    "utc",
    "validate",
    "verify",
    "verifyConsentChain",
    "verifyEnvelope",
    "verifyManifest",
  ];
  assert.equal(previousExports.length, 51);
  assert.deepEqual(Object.keys(core).sort(), [...previousExports, "markdownDestinations"].sort());
  assert.equal(typeof core.markdownDestinations, "function");
  const text = "](<https://a.example/>)\n[a]: https://b.example/ <https://c.example/>";
  assert.deepEqual(core.markdownDestinations(text), previousDestinations(text));
  const noCoercion = {
    get length() {
      throw new Error("length must not be read");
    },
    toString() {
      throw new Error("must not coerce");
    },
  };
  for (const value of [
    undefined,
    null,
    0,
    true,
    1n,
    Symbol("synthetic"),
    [],
    {},
    new String("text"),
    noCoercion,
  ])
    assert.throws(() => core.markdownDestinations(value), {
      name: "TypeError",
      message: "Markdown text must be a string.",
    });
});

async function signedReportFixture() {
  const owner = "synthetic_markdown_owner",
    vault = "synthetic_markdown_vault";
  const base = { contractVersion: core.CONTRACT, ownerSubject: owner, vaultId: vault };
  async function pair() {
    const p = await core.jose.generateKeyPair("ES256", { extractable: true });
    const all = await core.jose.exportJWK(p.publicKey);
    const publicJwk = Object.fromEntries(["kty", "crv", "x", "y"].map((k) => [k, all[k]]));
    return { ...p, publicJwk, kid: await core.keyId(publicJwk) };
  }
  const root = await pair(),
    keys = {},
    entries = [],
    descriptions = [];
  for (const role of ["device_sig", "device_enc", "recovery_enc", "agent_sig", "agent_enc"]) {
    const key = await pair();
    keys[role] = key;
    const cert = {
      ...base,
      artifactType: "key_certificate",
      certificateId: "certificate_" + role,
      keyId: key.kid,
      role,
      publicJwk: key.publicJwk,
      principalId: role.startsWith("agent")
        ? "agent_A"
        : role.startsWith("device")
          ? "device_A"
          : "recovery_A",
      connectionId: role.startsWith("agent") ? "connection_A" : null,
      keyEpoch: 1,
      issuerKeyId: root.kid,
      notBefore: 100,
      expiresAt: 5000,
      capabilities:
        role === "device_sig"
          ? ["object_write", "task_grant", "control_write"]
          : role === "agent_sig"
            ? ["run_request", "result_write"]
            : [],
    };
    entries.push({
      certificate: await core.sign(cert, root.privateKey, root.kid, "fv-control+jws"),
      active: true,
    });
    descriptions.push({
      certificateId: cert.certificateId,
      payloadDigest: await core.digest(cert),
      active: true,
    });
  }
  descriptions.sort((a, b) =>
    a.certificateId < b.certificateId ? -1 : a.certificateId > b.certificateId ? 1 : 0,
  );
  const checkpoint = {
    ...base,
    artifactType: "registry_checkpoint",
    rootKeyId: root.kid,
    rootEpoch: 1,
    registrySequence: 1,
    previousDigest: null,
    entriesDigest: await core.digest(descriptions),
    keyEpoch: 1,
    revokedKeyIds: [],
    issuedAt: 500,
  };
  const checkpointDigest = await core.digest(checkpoint);
  const bundle = {
    contractVersion: core.CONTRACT,
    checkpoint: await core.sign(checkpoint, root.privateKey, root.kid, "fv-control+jws"),
    entries,
  };
  const anchor = {
    ...base,
    rootJwk: root.publicJwk,
    rootKeyId: root.kid,
    rootEpoch: 1,
    registrySequence: 1,
    checkpointDigest,
  };
  delete anchor.contractVersion;
  const registry = await new core.Registry(anchor).load([bundle], 1000);
  const bindingPayload = {
    ...base,
    artifactType: "persistent_agent_binding",
    profile: "folioview.persistent-agent-identity.v1",
    rootKeyId: root.kid,
    connectionId: "connection_A",
    agentId: "agent_A",
    clientId: "muse_synthetic",
    identityEpoch: 1,
    agentSigningKeyId: keys.agent_sig.kid,
    agentEncryptionKeyId: keys.agent_enc.kid,
    deviceSigningKeyId: keys.device_sig.kid,
    stableOperationId: "synthetic_markdown_identity_01",
    registrySequence: 1,
    checkpointDigest,
    keyEpoch: 1,
    issuedAt: 950,
  };
  const binding = await core.sign(
    bindingPayload,
    keys.device_sig.privateKey,
    keys.device_sig.kid,
    "fv-control+jws",
  );
  const identity = {
    ...base,
    profile: "folioview.persistent-agent-identity.v1",
    ...Object.fromEntries(
      core.BINDING.filter((k) => k !== "bindingFingerprint").map((k) => [k, bindingPayload[k]]),
    ),
    bindingFingerprint: await core.fingerprint(binding),
    status: "active",
    registeredAt: 950,
    revokedAt: null,
  };
  await registry.binding(binding, identity, identity, 1000);
  const context = {
    ...base,
    profile: core.PROFILE,
    ...Object.fromEntries(core.BINDING.map((k) => [k, identity[k]])),
    registrySequence: 1,
    checkpointDigest,
    keyEpoch: 1,
    stableOperationId: "synthetic_markdown_report_0001",
    issuedAt: 1000,
    objectId: "synthetic_report",
    objectType: "result_revision",
    revision: 1,
    expectedRevision: 0,
    recipients: ["device_enc", "recovery_enc"]
      .map((role) => ({ keyId: keys[role].kid, role }))
      .sort((a, b) => (a.keyId < b.keyId ? -1 : a.keyId > b.keyId ? 1 : 0)),
    taskId: "synthetic_task",
    taskVersion: 1,
    executionEpoch: 1,
    authorityId: "synthetic_authority",
    authorityVersion: 1,
    purpose: "save_report",
    runId: "synthetic_run",
    manifestFingerprint: "2".repeat(64),
  };
  const publicKeys = Object.fromEntries(
    ["device_enc", "recovery_enc"].map((role) => [keys[role].kid, keys[role].publicJwk]),
  );
  const privateJwk = await core.jose.exportJWK(keys.device_enc.privateKey);
  const reader = await core.jose.importJWK(privateJwk, "ECDH-ES+A256KW");
  return {
    registry,
    identity,
    context,
    publicKeys,
    signer: keys.agent_sig.privateKey,
    reader,
    anchor,
    bundle,
  };
}

test(
  "genuine signed encrypted reports keep all private-byte and crypto boundaries",
  { timeout: 10000 },
  async () => {
    const f = await signedReportFixture();
    const value = report("");
    value.sections = Array.from({ length: 6 }, (_, i) => ({
      sectionId: "s" + i,
      markdown: "<a:" + "a:".repeat(7498),
    }));
    const options = {
      registry: f.registry,
      identity: f.identity,
      expected: f.context,
      now: 1000,
      purpose: "new_publication",
    };
    const envelope = await core.seal(value, f.context, f.publicKeys, f.signer);
    await core.verifyEnvelope(envelope, options);
    assert.deepEqual(await core.open(envelope, f.reader, f.context), value);
    const changed = structuredClone(envelope);
    const tag = Buffer.from(changed.jwe.tag, "base64url");
    tag[0] ^= 1;
    changed.jwe.tag = tag.toString("base64url");
    await assert.rejects(() => core.verifyEnvelope(changed, options));
    await assert.rejects(() => core.verifyEnvelope(envelope, { ...options, now: 5001 }));
    await assert.rejects(() =>
      new core.Registry({ ...f.anchor, rootKeyId: "A".repeat(43) }).load([f.bundle], 1000),
    );

    const wrapper = (payload) => ({
      privateSchemaVersion: 1,
      profile: core.PROFILE,
      objectId: f.context.objectId,
      objectType: "result_revision",
      revision: 1,
      payload,
    });
    value.sections.push({ sectionId: "padding", markdown: "" });
    value.sections.at(-1).markdown = "a".repeat(98304 - core.canonical(wrapper(value)).length);
    assert.equal(core.canonical(wrapper(value)).length, 98304);
    const maximum = await core.seal(value, f.context, f.publicKeys, f.signer);
    await core.verifyEnvelope(maximum, options);
    assert.deepEqual(await core.open(maximum, f.reader, f.context), value);
    value.sections.at(-1).markdown += "a";
    await assert.rejects(() => core.seal(value, f.context, f.publicKeys, f.signer), {
      code: "payload_too_large",
    });
  },
);
