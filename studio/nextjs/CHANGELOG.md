## 1.0.0

* First Next.js half of the studio SDK. Pages: `/studio/print` (print
  jobs board), `/studio/print/[job]` (production fields, Make press-ready:
  press PDF, imposed sheet, job ticket), `/studio/preflight` (client PDF
  preflight + imposition), `/studio/review/[token]` (public client proof
  review), `/studio/settings/hot-folder`. Components: `ConstructionPanel`
  (construction guides toggle) and `ProofPanel` (download or email a proof
  for sign-off). Server actions in `app/actions/studio/print-shop.ts` call
  only studio's own whitelisted cmds.
