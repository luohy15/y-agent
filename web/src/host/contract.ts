// Decision D6 (pages/decision-2412-runtime-contract.md, ruled in
// pages/review-2412-web-host-sdk.md): the `@y/host` contract version and the
// externals list have one physical copy, `cli/src/yagent/sdk/contract.json`
// (the CLI's editable install resolves the SDK directory relative to the
// installed module, so it must live under `cli/`), so the SDK materialized
// for `y module publish` and the deployed web host can never disagree within a
// release.
import contract from "../../../cli/src/yagent/sdk/contract.json";

export const HOST_CONTRACT_VERSION: number = contract.version;

export const EXTERNALS: readonly string[] = contract.externals;

export const MODULE_ICON_KEYS: readonly string[] = contract.icons;
