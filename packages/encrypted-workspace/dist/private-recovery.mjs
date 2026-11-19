var X = Object.create;
var z = Object.defineProperty;
var Y = Object.getOwnPropertyDescriptor;
var F = Object.getOwnPropertyNames;
var G = Object.getPrototypeOf,
  J = Object.prototype.hasOwnProperty;
var N = (e, i) => () => {
  try {
    return (i || e((i = { exports: {} }).exports, i), i.exports);
  } catch (f) {
    throw ((i = 0), f);
  }
};
var Q = (e, i, f, d) => {
  if ((i && typeof i == "object") || typeof i == "function")
    for (let a of F(i))
      !J.call(e, a) &&
        a !== f &&
        z(e, a, { get: () => i[a], enumerable: !(d = Y(i, a)) || d.enumerable });
  return e;
};
var U = (e, i, f) => (
  (f = e != null ? X(G(e)) : {}),
  Q(i || !e || !e.__esModule ? z(f, "default", { value: e, enumerable: !0 }) : f, e)
);
var Z = N((K) => {
  "use strict";
  Object.defineProperty(K, "__esModule", { value: !0 });
  function O(e) {
    let i = e.length,
      f = 0,
      d = 0,
      a;
    for (; d < i;)
      (f++,
        (a = e.charCodeAt(d++)),
        a >= 55296 && a <= 56319 && d < i && ((a = e.charCodeAt(d)), (a & 64512) === 56320 && d++));
    return f;
  }
  K.default = O;
  O.code = 'require("ajv/dist/runtime/ucs2length").default';
});
var T = N((A) => {
  "use strict";
  A.PrivateRecoveryRequest = q;
  var S = Z().default,
    W = new RegExp("^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", "u");
  function y(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = y.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (typeof e == "string") {
        if (S(e) > 128)
          return (
            (y.errors = [
              {
                instancePath: i,
                schemaPath: "#/maxLength",
                keyword: "maxLength",
                params: { limit: 128 },
              },
            ]),
            !1
          );
        if (S(e) < 1)
          return (
            (y.errors = [
              {
                instancePath: i,
                schemaPath: "#/minLength",
                keyword: "minLength",
                params: { limit: 1 },
              },
            ]),
            !1
          );
        if (!W.test(e))
          return (
            (y.errors = [
              {
                instancePath: i,
                schemaPath: "#/pattern",
                keyword: "pattern",
                params: { pattern: "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$" },
              },
            ]),
            !1
          );
      } else
        return (
          (y.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "string" } },
          ]),
          !1
        );
    return ((y.errors = r), t === 0);
  }
  y.evaluated = { dynamicProps: !1, dynamicItems: !1 };
  var ee = new RegExp("^[A-Za-z0-9_-]+$", "u");
  function D(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = D.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (typeof e == "string") {
        if (S(e) > 128)
          return (
            (D.errors = [
              {
                instancePath: i,
                schemaPath: "#/maxLength",
                keyword: "maxLength",
                params: { limit: 128 },
              },
            ]),
            !1
          );
        if (S(e) < 22)
          return (
            (D.errors = [
              {
                instancePath: i,
                schemaPath: "#/minLength",
                keyword: "minLength",
                params: { limit: 22 },
              },
            ]),
            !1
          );
        if (!ee.test(e))
          return (
            (D.errors = [
              {
                instancePath: i,
                schemaPath: "#/pattern",
                keyword: "pattern",
                params: { pattern: "^[A-Za-z0-9_-]+$" },
              },
            ]),
            !1
          );
      } else
        return (
          (D.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "string" } },
          ]),
          !1
        );
    return ((D.errors = r), t === 0);
  }
  D.evaluated = { dynamicProps: !1, dynamicItems: !1 };
  var re = new RegExp("^[A-Za-z0-9_-]{43}$", "u");
  function g(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = g.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (typeof e == "string") {
        if (S(e) > 43)
          return (
            (g.errors = [
              {
                instancePath: i,
                schemaPath: "#/maxLength",
                keyword: "maxLength",
                params: { limit: 43 },
              },
            ]),
            !1
          );
        if (S(e) < 43)
          return (
            (g.errors = [
              {
                instancePath: i,
                schemaPath: "#/minLength",
                keyword: "minLength",
                params: { limit: 43 },
              },
            ]),
            !1
          );
        if (!re.test(e))
          return (
            (g.errors = [
              {
                instancePath: i,
                schemaPath: "#/pattern",
                keyword: "pattern",
                params: { pattern: "^[A-Za-z0-9_-]{43}$" },
              },
            ]),
            !1
          );
      } else
        return (
          (g.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "string" } },
          ]),
          !1
        );
    return ((g.errors = r), t === 0);
  }
  g.evaluated = { dynamicProps: !1, dynamicItems: !1 };
  function w(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = w.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (e && typeof e == "object" && !Array.isArray(e)) {
        let u;
        if (
          (e.contractVersion === void 0 && (u = "contractVersion")) ||
          (e.profile === void 0 && (u = "profile")) ||
          (e.ownerSubject === void 0 && (u = "ownerSubject")) ||
          (e.vaultId === void 0 && (u = "vaultId")) ||
          (e.nonce === void 0 && (u = "nonce")) ||
          (e.deviceId === void 0 && (u = "deviceId")) ||
          (e.deviceSigningKeyId === void 0 && (u = "deviceSigningKeyId")) ||
          (e.deviceEncryptionKeyId === void 0 && (u = "deviceEncryptionKeyId"))
        )
          return (
            (w.errors = [
              {
                instancePath: i,
                schemaPath: "#/required",
                keyword: "required",
                params: { missingProperty: u },
              },
            ]),
            !1
          );
        {
          let p = t;
          for (let o in e)
            if (!(
              o === "contractVersion" ||
              o === "profile" ||
              o === "ownerSubject" ||
              o === "vaultId" ||
              o === "nonce" ||
              o === "deviceId" ||
              o === "deviceSigningKeyId" ||
              o === "deviceEncryptionKeyId"
            )) {
              return (
                (w.errors = [
                  {
                    instancePath: i,
                    schemaPath: "#/additionalProperties",
                    keyword: "additionalProperties",
                    params: { additionalProperty: o },
                  },
                ]),
                !1
              );
              break;
            }
          if (p === t) {
            if (e.contractVersion !== void 0) {
              let o = t;
              if (e.contractVersion !== "folioview.agent-workspace.v2.0")
                return (
                  (w.errors = [
                    {
                      instancePath: i + "/contractVersion",
                      schemaPath: "#/properties/contractVersion/const",
                      keyword: "const",
                      params: { allowedValue: "folioview.agent-workspace.v2.0" },
                    },
                  ]),
                  !1
                );
              var s = o === t;
            } else var s = !0;
            if (s) {
              if (e.profile !== void 0) {
                let o = t;
                if (e.profile !== "folioview.owner-recovery-evidence.v1")
                  return (
                    (w.errors = [
                      {
                        instancePath: i + "/profile",
                        schemaPath: "#/properties/profile/const",
                        keyword: "const",
                        params: { allowedValue: "folioview.owner-recovery-evidence.v1" },
                      },
                    ]),
                    !1
                  );
                var s = o === t;
              } else var s = !0;
              if (s) {
                if (e.ownerSubject !== void 0) {
                  let o = t;
                  y(e.ownerSubject, {
                    instancePath: i + "/ownerSubject",
                    parentData: e,
                    parentDataProperty: "ownerSubject",
                    rootData: a,
                    dynamicAnchors: l,
                  }) || ((r = r === null ? y.errors : r.concat(y.errors)), (t = r.length));
                  var s = o === t;
                } else var s = !0;
                if (s) {
                  if (e.vaultId !== void 0) {
                    let o = t;
                    y(e.vaultId, {
                      instancePath: i + "/vaultId",
                      parentData: e,
                      parentDataProperty: "vaultId",
                      rootData: a,
                      dynamicAnchors: l,
                    }) || ((r = r === null ? y.errors : r.concat(y.errors)), (t = r.length));
                    var s = o === t;
                  } else var s = !0;
                  if (s) {
                    if (e.nonce !== void 0) {
                      let o = t;
                      D(e.nonce, {
                        instancePath: i + "/nonce",
                        parentData: e,
                        parentDataProperty: "nonce",
                        rootData: a,
                        dynamicAnchors: l,
                      }) || ((r = r === null ? D.errors : r.concat(D.errors)), (t = r.length));
                      var s = o === t;
                    } else var s = !0;
                    if (s) {
                      if (e.deviceId !== void 0) {
                        let o = t;
                        y(e.deviceId, {
                          instancePath: i + "/deviceId",
                          parentData: e,
                          parentDataProperty: "deviceId",
                          rootData: a,
                          dynamicAnchors: l,
                        }) || ((r = r === null ? y.errors : r.concat(y.errors)), (t = r.length));
                        var s = o === t;
                      } else var s = !0;
                      if (s) {
                        if (e.deviceSigningKeyId !== void 0) {
                          let o = t;
                          g(e.deviceSigningKeyId, {
                            instancePath: i + "/deviceSigningKeyId",
                            parentData: e,
                            parentDataProperty: "deviceSigningKeyId",
                            rootData: a,
                            dynamicAnchors: l,
                          }) || ((r = r === null ? g.errors : r.concat(g.errors)), (t = r.length));
                          var s = o === t;
                        } else var s = !0;
                        if (s)
                          if (e.deviceEncryptionKeyId !== void 0) {
                            let o = t;
                            g(e.deviceEncryptionKeyId, {
                              instancePath: i + "/deviceEncryptionKeyId",
                              parentData: e,
                              parentDataProperty: "deviceEncryptionKeyId",
                              rootData: a,
                              dynamicAnchors: l,
                            }) ||
                              ((r = r === null ? g.errors : r.concat(g.errors)), (t = r.length));
                            var s = o === t;
                          } else var s = !0;
                      }
                    }
                  }
                }
              }
            }
          }
        }
      } else
        return (
          (w.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "object" } },
          ]),
          !1
        );
    return ((w.errors = r), t === 0);
  }
  w.evaluated = { props: !0, dynamicProps: !1, dynamicItems: !1 };
  function q(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = q.evaluated;
    return (
      n.dynamicProps && (n.props = void 0),
      n.dynamicItems && (n.items = void 0),
      w(e, {
        instancePath: i,
        parentData: f,
        parentDataProperty: d,
        rootData: a,
        dynamicAnchors: l,
      }) || ((r = r === null ? w.errors : r.concat(w.errors)), (t = r.length)),
      (q.errors = r),
      t === 0
    );
  }
  q.evaluated = { props: !0, dynamicProps: !1, dynamicItems: !1 };
  A.PrivateRecoveryEvidence = V;
  var C = {
      type: "object",
      properties: {
        contractVersion: { const: "folioview.agent-workspace.v2.0" },
        profile: { const: "folioview.owner-recovery-evidence.v1" },
        ownerSubject: { $ref: "#/$defs/Identifier" },
        vaultId: { $ref: "#/$defs/Identifier" },
        rootKeyId: { $ref: "#/$defs/KeyId" },
        requestDigest: { $ref: "#/$defs/Digest" },
        vaultVersion: { $ref: "#/$defs/PrivateResourceVersion" },
        registry: { $ref: "#/$defs/PrivateRegistryHead" },
        archive: { $ref: "#/$defs/PrivateArchiveBoundary" },
        device: { enum: ["active", "inactive"] },
        sourcesDigest: { $ref: "#/$defs/Digest" },
        verifiedAt: { $ref: "#/$defs/PrivateResourceTime" },
        expiresAt: { $ref: "#/$defs/PrivateResourceVersion" },
        registryStart: { oneOf: [{ $ref: "#/$defs/PrivateRegistryHead" }, { type: "null" }] },
      },
      required: [
        "contractVersion",
        "profile",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "requestDigest",
        "vaultVersion",
        "registry",
        "archive",
        "device",
        "sourcesDigest",
        "verifiedAt",
        "expiresAt",
        "registryStart",
      ],
      additionalProperties: !1,
    },
    te = Object.prototype.hasOwnProperty,
    ie = new RegExp("^[a-f0-9]{64}$", "u");
  function m(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = m.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (typeof e == "string") {
        if (S(e) > 64)
          return (
            (m.errors = [
              {
                instancePath: i,
                schemaPath: "#/maxLength",
                keyword: "maxLength",
                params: { limit: 64 },
              },
            ]),
            !1
          );
        if (S(e) < 64)
          return (
            (m.errors = [
              {
                instancePath: i,
                schemaPath: "#/minLength",
                keyword: "minLength",
                params: { limit: 64 },
              },
            ]),
            !1
          );
        if (!ie.test(e))
          return (
            (m.errors = [
              {
                instancePath: i,
                schemaPath: "#/pattern",
                keyword: "pattern",
                params: { pattern: "^[a-f0-9]{64}$" },
              },
            ]),
            !1
          );
      } else
        return (
          (m.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "string" } },
          ]),
          !1
        );
    return ((m.errors = r), t === 0);
  }
  m.evaluated = { dynamicProps: !1, dynamicItems: !1 };
  function v(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = v.evaluated;
    if (
      (n.dynamicProps && (n.props = void 0),
      n.dynamicItems && (n.items = void 0),
      !(typeof e == "number" && !(e % 1) && !isNaN(e)))
    )
      return (
        (v.errors = [
          { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "integer" } },
        ]),
        !1
      );
    if (t === 0 && typeof e == "number") {
      if (e > 9007199254740991 || isNaN(e))
        return (
          (v.errors = [
            {
              instancePath: i,
              schemaPath: "#/maximum",
              keyword: "maximum",
              params: { comparison: "<=", limit: 9007199254740991 },
            },
          ]),
          !1
        );
      if (e < 1 || isNaN(e))
        return (
          (v.errors = [
            {
              instancePath: i,
              schemaPath: "#/minimum",
              keyword: "minimum",
              params: { comparison: ">=", limit: 1 },
            },
          ]),
          !1
        );
    }
    return ((v.errors = r), t === 0);
  }
  v.evaluated = { dynamicProps: !1, dynamicItems: !1 };
  function P(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = P.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (e && typeof e == "object" && !Array.isArray(e)) {
        let u;
        if (
          (e.registryEpoch === void 0 && (u = "registryEpoch")) ||
          (e.registrySequence === void 0 && (u = "registrySequence")) ||
          (e.checkpointDigest === void 0 && (u = "checkpointDigest")) ||
          (e.keyEpoch === void 0 && (u = "keyEpoch"))
        )
          return (
            (P.errors = [
              {
                instancePath: i,
                schemaPath: "#/required",
                keyword: "required",
                params: { missingProperty: u },
              },
            ]),
            !1
          );
        {
          let p = t;
          for (let o in e)
            if (!(
              o === "registryEpoch" ||
              o === "registrySequence" ||
              o === "checkpointDigest" ||
              o === "keyEpoch"
            )) {
              return (
                (P.errors = [
                  {
                    instancePath: i,
                    schemaPath: "#/additionalProperties",
                    keyword: "additionalProperties",
                    params: { additionalProperty: o },
                  },
                ]),
                !1
              );
              break;
            }
          if (p === t) {
            if (e.registryEpoch !== void 0) {
              let o = t;
              v(e.registryEpoch, {
                instancePath: i + "/registryEpoch",
                parentData: e,
                parentDataProperty: "registryEpoch",
                rootData: a,
                dynamicAnchors: l,
              }) || ((r = r === null ? v.errors : r.concat(v.errors)), (t = r.length));
              var s = o === t;
            } else var s = !0;
            if (s) {
              if (e.registrySequence !== void 0) {
                let o = t;
                v(e.registrySequence, {
                  instancePath: i + "/registrySequence",
                  parentData: e,
                  parentDataProperty: "registrySequence",
                  rootData: a,
                  dynamicAnchors: l,
                }) || ((r = r === null ? v.errors : r.concat(v.errors)), (t = r.length));
                var s = o === t;
              } else var s = !0;
              if (s) {
                if (e.checkpointDigest !== void 0) {
                  let o = t;
                  m(e.checkpointDigest, {
                    instancePath: i + "/checkpointDigest",
                    parentData: e,
                    parentDataProperty: "checkpointDigest",
                    rootData: a,
                    dynamicAnchors: l,
                  }) || ((r = r === null ? m.errors : r.concat(m.errors)), (t = r.length));
                  var s = o === t;
                } else var s = !0;
                if (s)
                  if (e.keyEpoch !== void 0) {
                    let o = t;
                    v(e.keyEpoch, {
                      instancePath: i + "/keyEpoch",
                      parentData: e,
                      parentDataProperty: "keyEpoch",
                      rootData: a,
                      dynamicAnchors: l,
                    }) || ((r = r === null ? v.errors : r.concat(v.errors)), (t = r.length));
                    var s = o === t;
                  } else var s = !0;
              }
            }
          }
        }
      } else
        return (
          (P.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "object" } },
          ]),
          !1
        );
    return ((P.errors = r), t === 0);
  }
  P.evaluated = { props: !0, dynamicProps: !1, dynamicItems: !1 };
  var se = {
    type: "object",
    properties: {
      state: { enum: ["active", "revoking", "deleted"] },
      version: { $ref: "#/$defs/PrivateResourceVersion" },
      digest: { $ref: "#/$defs/Digest" },
    },
    required: ["state", "version", "digest"],
    additionalProperties: !1,
  };
  function k(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = k.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (e && typeof e == "object" && !Array.isArray(e)) {
        let u;
        if (
          (e.state === void 0 && (u = "state")) ||
          (e.version === void 0 && (u = "version")) ||
          (e.digest === void 0 && (u = "digest"))
        )
          return (
            (k.errors = [
              {
                instancePath: i,
                schemaPath: "#/required",
                keyword: "required",
                params: { missingProperty: u },
              },
            ]),
            !1
          );
        {
          let p = t;
          for (let o in e)
            if (!(o === "state" || o === "version" || o === "digest")) {
              return (
                (k.errors = [
                  {
                    instancePath: i,
                    schemaPath: "#/additionalProperties",
                    keyword: "additionalProperties",
                    params: { additionalProperty: o },
                  },
                ]),
                !1
              );
              break;
            }
          if (p === t) {
            if (e.state !== void 0) {
              let o = e.state,
                c = t;
              if (!(o === "active" || o === "revoking" || o === "deleted"))
                return (
                  (k.errors = [
                    {
                      instancePath: i + "/state",
                      schemaPath: "#/properties/state/enum",
                      keyword: "enum",
                      params: { allowedValues: se.properties.state.enum },
                    },
                  ]),
                  !1
                );
              var s = c === t;
            } else var s = !0;
            if (s) {
              if (e.version !== void 0) {
                let o = t;
                v(e.version, {
                  instancePath: i + "/version",
                  parentData: e,
                  parentDataProperty: "version",
                  rootData: a,
                  dynamicAnchors: l,
                }) || ((r = r === null ? v.errors : r.concat(v.errors)), (t = r.length));
                var s = o === t;
              } else var s = !0;
              if (s)
                if (e.digest !== void 0) {
                  let o = t;
                  m(e.digest, {
                    instancePath: i + "/digest",
                    parentData: e,
                    parentDataProperty: "digest",
                    rootData: a,
                    dynamicAnchors: l,
                  }) || ((r = r === null ? m.errors : r.concat(m.errors)), (t = r.length));
                  var s = o === t;
                } else var s = !0;
            }
          }
        }
      } else
        return (
          (k.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "object" } },
          ]),
          !1
        );
    return ((k.errors = r), t === 0);
  }
  k.evaluated = { props: !0, dynamicProps: !1, dynamicItems: !1 };
  function _(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = _.evaluated;
    if (
      (n.dynamicProps && (n.props = void 0),
      n.dynamicItems && (n.items = void 0),
      !(typeof e == "number" && !(e % 1) && !isNaN(e)))
    )
      return (
        (_.errors = [
          { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "integer" } },
        ]),
        !1
      );
    if (t === 0 && typeof e == "number") {
      if (e > 9007199254740991 || isNaN(e))
        return (
          (_.errors = [
            {
              instancePath: i,
              schemaPath: "#/maximum",
              keyword: "maximum",
              params: { comparison: "<=", limit: 9007199254740991 },
            },
          ]),
          !1
        );
      if (e < 0 || isNaN(e))
        return (
          (_.errors = [
            {
              instancePath: i,
              schemaPath: "#/minimum",
              keyword: "minimum",
              params: { comparison: ">=", limit: 0 },
            },
          ]),
          !1
        );
    }
    return ((_.errors = r), t === 0);
  }
  _.evaluated = { dynamicProps: !1, dynamicItems: !1 };
  function h(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = h.evaluated;
    if ((n.dynamicProps && (n.props = void 0), n.dynamicItems && (n.items = void 0), t === 0))
      if (e && typeof e == "object" && !Array.isArray(e)) {
        let p;
        if (
          (e.contractVersion === void 0 && (p = "contractVersion")) ||
          (e.profile === void 0 && (p = "profile")) ||
          (e.ownerSubject === void 0 && (p = "ownerSubject")) ||
          (e.vaultId === void 0 && (p = "vaultId")) ||
          (e.rootKeyId === void 0 && (p = "rootKeyId")) ||
          (e.requestDigest === void 0 && (p = "requestDigest")) ||
          (e.vaultVersion === void 0 && (p = "vaultVersion")) ||
          (e.registry === void 0 && (p = "registry")) ||
          (e.archive === void 0 && (p = "archive")) ||
          (e.device === void 0 && (p = "device")) ||
          (e.sourcesDigest === void 0 && (p = "sourcesDigest")) ||
          (e.verifiedAt === void 0 && (p = "verifiedAt")) ||
          (e.expiresAt === void 0 && (p = "expiresAt")) ||
          (e.registryStart === void 0 && (p = "registryStart"))
        )
          return (
            (h.errors = [
              {
                instancePath: i,
                schemaPath: "#/required",
                keyword: "required",
                params: { missingProperty: p },
              },
            ]),
            !1
          );
        {
          let o = t;
          for (let c in e)
            if (!te.call(C.properties, c)) {
              return (
                (h.errors = [
                  {
                    instancePath: i,
                    schemaPath: "#/additionalProperties",
                    keyword: "additionalProperties",
                    params: { additionalProperty: c },
                  },
                ]),
                !1
              );
              break;
            }
          if (o === t) {
            if (e.contractVersion !== void 0) {
              let c = t;
              if (e.contractVersion !== "folioview.agent-workspace.v2.0")
                return (
                  (h.errors = [
                    {
                      instancePath: i + "/contractVersion",
                      schemaPath: "#/properties/contractVersion/const",
                      keyword: "const",
                      params: { allowedValue: "folioview.agent-workspace.v2.0" },
                    },
                  ]),
                  !1
                );
              var s = c === t;
            } else var s = !0;
            if (s) {
              if (e.profile !== void 0) {
                let c = t;
                if (e.profile !== "folioview.owner-recovery-evidence.v1")
                  return (
                    (h.errors = [
                      {
                        instancePath: i + "/profile",
                        schemaPath: "#/properties/profile/const",
                        keyword: "const",
                        params: { allowedValue: "folioview.owner-recovery-evidence.v1" },
                      },
                    ]),
                    !1
                  );
                var s = c === t;
              } else var s = !0;
              if (s) {
                if (e.ownerSubject !== void 0) {
                  let c = t;
                  y(e.ownerSubject, {
                    instancePath: i + "/ownerSubject",
                    parentData: e,
                    parentDataProperty: "ownerSubject",
                    rootData: a,
                    dynamicAnchors: l,
                  }) || ((r = r === null ? y.errors : r.concat(y.errors)), (t = r.length));
                  var s = c === t;
                } else var s = !0;
                if (s) {
                  if (e.vaultId !== void 0) {
                    let c = t;
                    y(e.vaultId, {
                      instancePath: i + "/vaultId",
                      parentData: e,
                      parentDataProperty: "vaultId",
                      rootData: a,
                      dynamicAnchors: l,
                    }) || ((r = r === null ? y.errors : r.concat(y.errors)), (t = r.length));
                    var s = c === t;
                  } else var s = !0;
                  if (s) {
                    if (e.rootKeyId !== void 0) {
                      let c = t;
                      g(e.rootKeyId, {
                        instancePath: i + "/rootKeyId",
                        parentData: e,
                        parentDataProperty: "rootKeyId",
                        rootData: a,
                        dynamicAnchors: l,
                      }) || ((r = r === null ? g.errors : r.concat(g.errors)), (t = r.length));
                      var s = c === t;
                    } else var s = !0;
                    if (s) {
                      if (e.requestDigest !== void 0) {
                        let c = t;
                        m(e.requestDigest, {
                          instancePath: i + "/requestDigest",
                          parentData: e,
                          parentDataProperty: "requestDigest",
                          rootData: a,
                          dynamicAnchors: l,
                        }) || ((r = r === null ? m.errors : r.concat(m.errors)), (t = r.length));
                        var s = c === t;
                      } else var s = !0;
                      if (s) {
                        if (e.vaultVersion !== void 0) {
                          let c = t;
                          v(e.vaultVersion, {
                            instancePath: i + "/vaultVersion",
                            parentData: e,
                            parentDataProperty: "vaultVersion",
                            rootData: a,
                            dynamicAnchors: l,
                          }) || ((r = r === null ? v.errors : r.concat(v.errors)), (t = r.length));
                          var s = c === t;
                        } else var s = !0;
                        if (s) {
                          if (e.registry !== void 0) {
                            let c = t;
                            P(e.registry, {
                              instancePath: i + "/registry",
                              parentData: e,
                              parentDataProperty: "registry",
                              rootData: a,
                              dynamicAnchors: l,
                            }) ||
                              ((r = r === null ? P.errors : r.concat(P.errors)), (t = r.length));
                            var s = c === t;
                          } else var s = !0;
                          if (s) {
                            if (e.archive !== void 0) {
                              let c = t;
                              k(e.archive, {
                                instancePath: i + "/archive",
                                parentData: e,
                                parentDataProperty: "archive",
                                rootData: a,
                                dynamicAnchors: l,
                              }) ||
                                ((r = r === null ? k.errors : r.concat(k.errors)), (t = r.length));
                              var s = c === t;
                            } else var s = !0;
                            if (s) {
                              if (e.device !== void 0) {
                                let c = e.device,
                                  x = t;
                                if (!(c === "active" || c === "inactive"))
                                  return (
                                    (h.errors = [
                                      {
                                        instancePath: i + "/device",
                                        schemaPath: "#/properties/device/enum",
                                        keyword: "enum",
                                        params: { allowedValues: C.properties.device.enum },
                                      },
                                    ]),
                                    !1
                                  );
                                var s = x === t;
                              } else var s = !0;
                              if (s) {
                                if (e.sourcesDigest !== void 0) {
                                  let c = t;
                                  m(e.sourcesDigest, {
                                    instancePath: i + "/sourcesDigest",
                                    parentData: e,
                                    parentDataProperty: "sourcesDigest",
                                    rootData: a,
                                    dynamicAnchors: l,
                                  }) ||
                                    ((r = r === null ? m.errors : r.concat(m.errors)),
                                    (t = r.length));
                                  var s = c === t;
                                } else var s = !0;
                                if (s) {
                                  if (e.verifiedAt !== void 0) {
                                    let c = t;
                                    _(e.verifiedAt, {
                                      instancePath: i + "/verifiedAt",
                                      parentData: e,
                                      parentDataProperty: "verifiedAt",
                                      rootData: a,
                                      dynamicAnchors: l,
                                    }) ||
                                      ((r = r === null ? _.errors : r.concat(_.errors)),
                                      (t = r.length));
                                    var s = c === t;
                                  } else var s = !0;
                                  if (s) {
                                    if (e.expiresAt !== void 0) {
                                      let c = t;
                                      v(e.expiresAt, {
                                        instancePath: i + "/expiresAt",
                                        parentData: e,
                                        parentDataProperty: "expiresAt",
                                        rootData: a,
                                        dynamicAnchors: l,
                                      }) ||
                                        ((r = r === null ? v.errors : r.concat(v.errors)),
                                        (t = r.length));
                                      var s = c === t;
                                    } else var s = !0;
                                    if (s)
                                      if (e.registryStart !== void 0) {
                                        let c = e.registryStart,
                                          x = t,
                                          j = t,
                                          E = !1,
                                          $ = null,
                                          H = t;
                                        P(c, {
                                          instancePath: i + "/registryStart",
                                          parentData: e,
                                          parentDataProperty: "registryStart",
                                          rootData: a,
                                          dynamicAnchors: l,
                                        }) ||
                                          ((r = r === null ? P.errors : r.concat(P.errors)),
                                          (t = r.length));
                                        var u = H === t;
                                        u && ((E = !0), ($ = 0));
                                        let M = t;
                                        if (c !== null) {
                                          let b = {
                                            instancePath: i + "/registryStart",
                                            schemaPath: "#/properties/registryStart/oneOf/1/type",
                                            keyword: "type",
                                            params: { type: "null" },
                                          };
                                          (r === null ? (r = [b]) : r.push(b), t++);
                                        }
                                        var u = M === t;
                                        if (
                                          (u && E
                                            ? ((E = !1), ($ = [$, 1]))
                                            : u && ((E = !0), ($ = 1)),
                                          E)
                                        )
                                          ((t = j),
                                            r !== null && (j ? (r.length = j) : (r = null)));
                                        else {
                                          let b = {
                                            instancePath: i + "/registryStart",
                                            schemaPath: "#/properties/registryStart/oneOf",
                                            keyword: "oneOf",
                                            params: { passingSchemas: $ },
                                          };
                                          return (
                                            r === null ? (r = [b]) : r.push(b),
                                            t++,
                                            (h.errors = r),
                                            !1
                                          );
                                        }
                                        var s = x === t;
                                      } else var s = !0;
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      } else
        return (
          (h.errors = [
            { instancePath: i, schemaPath: "#/type", keyword: "type", params: { type: "object" } },
          ]),
          !1
        );
    return ((h.errors = r), t === 0);
  }
  h.evaluated = { props: !0, dynamicProps: !1, dynamicItems: !1 };
  function V(
    e,
    {
      instancePath: i = "",
      parentData: f,
      parentDataProperty: d,
      rootData: a = e,
      dynamicAnchors: l = {},
    } = {},
  ) {
    let r = null,
      t = 0,
      n = V.evaluated;
    return (
      n.dynamicProps && (n.props = void 0),
      n.dynamicItems && (n.items = void 0),
      h(e, {
        instancePath: i,
        parentData: f,
        parentDataProperty: d,
        rootData: a,
        dynamicAnchors: l,
      }) || ((r = r === null ? h.errors : r.concat(h.errors)), (t = r.length)),
      (V.errors = r),
      t === 0
    );
  }
  V.evaluated = { props: !0, dynamicProps: !1, dynamicItems: !1 };
});
var B = U(T(), 1);
import {
  canonical as ne,
  deny as I,
  digest as oe,
  integer as ae,
  parsed as le,
  same as L,
  validate as ce,
} from "../dist/core.mjs";
var fe = 16384,
  ue = 60,
  pe = ["registryEpoch", "registrySequence", "keyEpoch"];
function R(e, i) {
  B.default[e](i) || I("invalid_schema");
  let f = ne(i);
  return (f.length > fe && I("payload_too_large"), le(f, !0));
}
async function ge(e, { request: i, pinnedRootKeyId: f, now: d, previous: a = null }) {
  (ae(d), ce("KeyId", f));
  let l = R("PrivateRecoveryRequest", i);
  e == null && I("authorization_unavailable");
  let r = R("PrivateRecoveryEvidence", e),
    t = a === null ? null : R("PrivateRecoveryEvidence", a);
  ((r.ownerSubject !== l.ownerSubject || r.vaultId !== l.vaultId) &&
    I("recipient_binding_mismatch"),
    r.rootKeyId !== f && I("untrusted_key"),
    r.requestDigest !== (await oe(l)) && I("recipient_binding_mismatch"),
    (r.verifiedAt > d || r.expiresAt <= d || r.expiresAt - r.verifiedAt > ue) &&
      I("authorization_unavailable"),
    (r.archive.state !== "active" || r.device !== "active") && I("key_authorization_required"));
  let n = r.registry,
    s = r.registryStart;
  if (
    (((n.registryEpoch === 1) != (s === null) ||
      (s !== null &&
        (n.registryEpoch !== s.registryEpoch ||
          n.registrySequence < s.registrySequence ||
          n.keyEpoch < s.keyEpoch ||
          (n.registrySequence === s.registrySequence && !L(n, s))))) &&
      I("registry_conflict"),
    t !== null)
  ) {
    ["ownerSubject", "vaultId", "rootKeyId"].some((p) => t[p] !== r[p]) &&
      I("recipient_binding_mismatch");
    let u = t.registry;
    (r.vaultVersion < t.vaultVersion ||
      r.archive.version < t.archive.version ||
      pe.some((p) => n[p] < u[p]) ||
      (n.registrySequence === u.registrySequence && !L(n, u)) ||
      (n.registryEpoch === u.registryEpoch && !L(s, t.registryStart))) &&
      I("rollback_detected");
  }
  return r;
}
export { ge as verifyOwnerRecoveryEvidence };
