import type {
  RegistryBundle,
  Signed,
  CONTRACT,
  OWNER_RECOVERY_PROFILE,
  OWNER_REGISTRY_PAGE_PROFILE,
} from "./encrypted-types";

export type PrivateRegistryHead = {
  registryEpoch: number;
  registrySequence: number;
  checkpointDigest: string;
  keyEpoch: number;
};

type RecoveryScope = { contractVersion: typeof CONTRACT; ownerSubject: string; vaultId: string };

export type OwnerRecoveryRequest = RecoveryScope & {
  profile: typeof OWNER_RECOVERY_PROFILE;
  nonce: string;
  deviceId: string;
  deviceSigningKeyId: string;
  deviceEncryptionKeyId: string;
};

export type OwnerRegistryPageRequest = RecoveryScope & {
  profile: typeof OWNER_REGISTRY_PAGE_PROFILE;
  base: PrivateRegistryHead;
  target: PrivateRegistryHead;
};

export type OwnerRecoveryProgress =
  | { status: "page"; request: OwnerRegistryPageRequest }
  | { status: "unchanged" | "registry-verified" | "refresh-required" };

export type OwnerRecoveryTransport = {
  evidence(request: OwnerRecoveryRequest, signal: AbortSignal): Promise<unknown>;
  page(request: OwnerRegistryPageRequest, signal: AbortSignal): Promise<unknown>;
};

export type RegistryTransitionReview = {
  operationId: string;
  vaultId: string;
  rootKeyId: string;
  previousHead: PrivateRegistryHead;
  archiveVersion: number;
  ownerKeyIds: string[];
  expiresAt: number;
};

export type RegistryTransitionPacket = {
  operationId: string;
  signedTransition: Signed;
  firstBundle: RegistryBundle;
};
